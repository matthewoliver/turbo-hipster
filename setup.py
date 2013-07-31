#!/usr/bin/env python
#
# Copyright 2013 Rackspace Australia
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import os
from setuptools import setup

# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "turbo-hipster",
    version = "0.0.1",
    author = "Joshua Hesketh",
    author_email = "josh@nitrotech.org",
    description = ("A set of CI tools for openstack."),
    license = "GPLv2",
    keywords = "",
    url = "https://github.com/rcbau/turbo-hipster",
    packages=['turbo_hipster', 'tests'],
    long_description=read('README.md'),
    classifiers=[
    ],
)
