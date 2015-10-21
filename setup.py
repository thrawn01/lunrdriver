#!/usr/bin/python
# Copyright (c) 2011 Rackspace US, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from setuptools import setup, find_packages

from lunrdriver import __canonical_version__ as version

name = 'lunrdriver'

setup(
    name=name,
    version=version,
    description='Lunr Driver',
    license='Apache License (2.0)',
    author='Rackspace US, Inc.',
    packages=find_packages(exclude=['testlunr']),
    test_suite='nose.collector',
    entry_points={
        'paste.filter_factory': [
            'rack_auth=lunrdriver.lunr.auth:filter_factory',
            'statlogger=lunrdriver.lunr.statlogger:filter_factory',
            ],
    }
)
