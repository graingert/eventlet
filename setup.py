#!/usr/bin/env python
from setuptools import find_packages, setup

from eventlet import __version__
from os import path, environ
import sys

tests_require = []

if environ.get("TRAVIS", False):
    tests_require = [
        "pyopenssl",
        "MySQL-python",
    ]

    if sys.version_info < (2, 6):
        tests_require.append("pyzmq<2.2")
    else:
        tests_require.append("pyzmq")

setup(
    name='eventlet',
    version=__version__,
    description='Highly concurrent networking library',
    author='Linden Lab',
    author_email='eventletdev@lists.secondlife.com',
    url='http://eventlet.net',
    packages=find_packages(exclude=['tests', 'benchmarks']),
    install_requires=(
        'greenlet >= 0.3',
    ),
    zip_safe=False,
    long_description=open(
        path.join(
            path.dirname(__file__),
            'README.rst'
        )
    ).read(),
    test_suite='nose.collector',
    tests_require=tests_require,
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 2.4",
        "Programming Language :: Python :: 2.5",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Topic :: Internet",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Intended Audience :: Developers",
        "Development Status :: 4 - Beta",
    ]
)
