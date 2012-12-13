"""The :mod:`zmq` module wraps the :class:`Socket` and :class:`Context`
found in :mod:`pyzmq <zmq>` to be non blocking.

Implementation notes: Each socket in 0mq contains a pipe that the
background IO threads use to communicate with the socket. These
events are important because they tell the socket when it is able to
send and when it has messages waiting to be received. The read end
of the events pipe is the same FD that getsockopt(zmq.FD) returns.

Events are read from the socket's event pipe only on the thread that
the 0mq context is associated with, which is the native thread the
greenthreads are running on, and the only operations that cause the
events to be read and processed are send(), recv() and
getsockopt(zmq.EVENTS). This means that after doing any of these
three operations, the ability of the socket to send or receive a
message without blocking may have changed, but after the events are
read the FD is no longer readable so the hub may not signal our
listener.
"""

from __future__ import with_statement

__zmq__ = __import__('zmq')
from eventlet import hubs, patcher, sleep, Timeout

__patched__ = ['Context', 'Socket']
patcher.slurp_properties(__zmq__, globals(), ignore=__patched__)

threading = patcher.original('threading')
_threadlocal = threading.local()


def Context(io_threads=1):
    """Factory function replacement for :class:`zmq.core.context.Context`
    This factory ensures the :class:`zeromq hub <eventlet.hubs.zeromq.Hub>`
    is the active hub, and defers creation (or retreival) of the ``Context``
    to the hub's :meth:`~eventlet.hubs.zeromq.Hub.get_context` method

    It's a factory function due to the fact that there can only be one :class:`_Context`
    instance per thread. This is due to the way :class:`zmq.core.poll.Poller`
    works
    """
    context = getattr(_threadlocal, 'context', None)
    if context is None or context.closed:
        _threadlocal.context = context = _Context(io_threads)
    return context


class _Context(__zmq__.Context):
    """Internal subclass of :class:`zmq.core.context.Context`

    .. warning:: Do not grab one of these yourself, use the factory function
        :func:`eventlet.green.zmq.Context`
    """
    def socket(self, socket_type):
        """Overridden method to ensure that the green version of socket is used

        Behaves the same as :meth:`zmq.core.context.Context.socket`, but ensures
        that a :class:`Socket` with all of its send and recv methods set to be
        non-blocking is returned
        """
        return Socket(self, socket_type)


def _socket_wait(socket, read=False, write=False):
    """Tries to do a wait that works around a couple race conditions.
    ZMQ is edge triggered, and the IO fd it uses can go off before eventlet can
    check for the IO event.  That means we need to trampoline only if
    necessary, only on READ, and we need to timeout the trampoline so we
    can catch the missed events and then try the recv/send again.
    """
    events = socket.getsockopt(__zmq__.EVENTS)

    if read and (events & __zmq__.POLLIN):
        return events
    elif write and (events & __zmq__.POLLOUT):
        return events
    else:
        # ONLY trampoline on read events for the zmq FD
        try:
            hubs.trampoline(socket.getsockopt(__zmq__.FD), read=True, timeout=0.1, _allow_multiple_readers=True)
        except Timeout:
            # this handle the edge case of missing the real event on the FD
            # event though zmq thinks there is none
            pass

        return socket.getsockopt(__zmq__.EVENTS)


def _nasty_call_wrapper(socket, func, read, flags, *args, **kw):
    """This is what its name implies:  A nasty set of work arounds to minimize
    a race condition between zmq and eventlet.  Basically, zmq will report
    that there are NO read events on a zmq socket, but by the time you
    trampoline you'll miss an event that comes in on the internal FD.  Since
    zmq is edge triggered and eventlet doesn't know to check the
    getsockopt(EVENTS), it then stalls.

    The solution is to try to read, catch the EAGAIN, then try to wait, but
    only if getsockopt(EVENTS) says you need to, and *then* also timeout the
    trampoline so that you exit when you miss an event.  In the event of a
    timeout then you try the read again and repeat the process.

    Kind of gross, but works and you only hit the 0.1 sleep time when
    there's this rare stall or if you're idle.
    """
    if flags & __zmq__.NOBLOCK:
        # explicitly requesting noblock to do it and return
        return func(*args, flags=flags, **kw)

    # we have to force a noblock on this so that we can do a lame
    # poll to work around a race condition between ZMQ and eventlet
    flags |= __zmq__.NOBLOCK

    while True:
        # Give other greenthreads a chance to run.
        sleep()
        try:
            m = func(*args, flags=flags, **kw)

            # there's a situation where a recv returns None but that means
            # try again, which is weird but whatever
            if read and m != None:
                return m
            elif not read:
                return
            # else: on this is to just try again
        except __zmq__.ZMQError, e:
            # we got an EAGAIN, so now we try to wait
            if e.errno == __zmq__.EAGAIN:
                _socket_wait(socket, write=not read, read=read)
            else:
                # well looks like something bad happened
                raise


class Socket(__zmq__.Socket):
    """Green version of :class:`zmq.core.socket.Socket

    The following four methods are overridden:

        * _send_message
        * _send_copy
        * _recv_message
        * _recv_copy

    To ensure that the ``zmq.NOBLOCK`` flag is set and that sending or recieving
    is deferred to the hub (using :func:`eventlet.hubs.trampoline`) if a
    ``zmq.EAGAIN`` (retry) error is raised.
    """
    def send(self, msg, flags=0, copy=True, track=False):
        """Override this instead of the internal _send_* methods
        since those change and it's not clear when/how they're
        called in real code.
        """
        return _nasty_call_wrapper(self, super(Socket, self).send,
            False, flags, msg, copy=True, track=False)

    def recv(self, flags=0, copy=True, track=False):
        """
        Override this instead of the internal _recv_* methods
        since those change and it's not clear when/how they're
        called in real code.
        """
        return _nasty_call_wrapper(self, super(Socket, self).recv,
            True, flags, copy=True, track=False)
