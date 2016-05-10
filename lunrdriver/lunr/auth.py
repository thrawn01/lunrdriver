# Copyright (c) 2011-2013 Rackspace US, Inc.
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


import json
import time
import urllib2
import redis
from datetime import datetime, timedelta
from collections import defaultdict
from webob.exc import HTTPUnauthorized, HTTPServiceUnavailable, HTTPNotFound

try:
    from oslo_log import log as logging
except ImportError:
    from cinder.openstack.common import log as logging

LOG = logging.getLogger('cinder.lunr.auth')


class InvalidUserToken(Exception):
    pass


class LogThrottler():

    def __init__(self, burst=5, timeLimit=5):
        self.timeLimit = timeLimit
        self.cache = defaultdict(int)
        self.timeWindow = None
        self.limit = burst
        self.count = 0
        self.start()

    def start(self):
        self.timeWindow = datetime.now() + timedelta(seconds=self.timeLimit)

    def error(self, message):
        self.log(message, logger=LOG.error)

    def info(self, message):
        self.log(message, logger=LOG.info)

    def debug(self, message):
        LOG.debug(message)

    def exception(self, message):
        self.log(message, logger=LOG.exception)

    def log(self, message, logger=LOG.info):
        if message in self.cache:
            count = self.cache[message]
            # Have reached our burst limit?
            if count > self.limit:
                # Are we inside our time limit?
                if self.timeWindow > datetime.now():
                    remain = (self.timeWindow - datetime.now()).total_seconds()
                    # Omit Logging this message
                    logger("%s - To many messages throttling for %d secs"
                           % (message, remain))
                    return
                else:
                    self.start()
                    del self.cache[message]
        self.cache[message] += 1
        logger(message)


class RackAuth(object):

    def __init__(self, conf, app):
        self.redis_host = conf.get('redis-host', '')
        self.redis = redis.StrictRedis(host=self.redis_host, port=6379, db=0)
        self.admin_user = conf.get('username', '')
        self.admin_pass = conf.get('password', '')
        self.admin_url = conf.get('url', '')
        self.log = LogThrottler()
        self._admin_token = None
        self.app = app

    @property
    def admin_token(self):
        if not self._admin_token:
            admin_info = self._auth_request('/v2.0/tokens', method='POST',
                                            admin_request=True)
            self._admin_token = admin_info['access']['token']['id']
        self.log.debug('admin_token is %r' % self._admin_token)
        return self._admin_token

    def _auth_request(self, path, method='GET', admin_request=False):
        """Make a request to auth

        :returns : dump of json response body

        :raises : urllib2.HTTPError
        """
        attempts = 3
        attempt = 0
        while True:
            attempt += 1
            headers = {'Content-Type': 'application/json',
                       'Accept': 'application/json',
                       'User-Agent': 'CloudBlockStorage (RackAuth)'}
            body = None
            if admin_request:
                # this request is to get an admin token
                body = json.dumps({
                    "auth": {
                        "passwordCredentials": {
                            "username": self.admin_user,
                            "password": self.admin_pass,
                        }
                    }
                })
            else:
                # this request requires a validate admin token
                headers['X-Auth-Token'] = self.admin_token
            req_path = self.admin_url + path
            self.log.debug('req_path: %s - headers: %s' % (req_path, headers))
            req = urllib2.Request(req_path, headers=headers, data=body)
            req.get_method = lambda *args: method
            try:
                resp = urllib2.urlopen(req)
                return json.loads(resp.read())
            except urllib2.HTTPError, e:
                if e.code == 401:
                    self._admin_token = None
                elif e.code == 404 and self._admin_token:
                    # 404 means invalid token, no retry
                    raise
            except Exception, e:
                pass
            if attempt >= attempts:
                raise
            self.log.exception('Failed validate token request, '
                               'attempt %s of %s' % (attempt, attempts))
            time.sleep(2 ** attempt)

    def get_token_info(self, token, account):
        """Check a token with auth

        :returns : an access dict

        e.g.

        token_info = {
            'access': {
                'token': {
                    'tenant': {
                        'name': 'account1',
                        'id': 'account1',
                    }
                },
                'user': {
                    'id': 'johnny', 'name': 'johnny',
                    'roles': [{'name': 'admin'}],
                }
            }
        }

        :raises : InvalidUserToken

        """
        token_info = self.cache_get(token)
        if token_info is None:
            path = '/v2.0/tokens/%s?belongsTo=%s' % (token, account)
            try:
                token_info = self._auth_request(path)
            except urllib2.HTTPError, e:
                if e.code == 404:
                    raise InvalidUserToken('token not found')
                else:
                    raise

        self.log.debug('token_info: %r' % token_info)

        tenant_info = token_info['access']['token']['tenant']
        if account not in (tenant_info['name'], tenant_info['id']):
            raise InvalidUserToken('token does not match tenant')

        self.cache_get.set(token, token_info, ex=self.redis_expire_secs)
        return token_info

    def get_headers(self, token_info):
        tenant_id = token_info['access']['token']['tenant']['id']
        tenant_name = token_info['access']['token']['tenant']['name']
        user_id = token_info['access']['user']['id']
        roles_list = token_info['access']['user'].get('roles', [])
        roles = ','.join([role['name'] for role in roles_list])

        headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Tenant-Id': tenant_id,
            'X-Tenant-Name': tenant_name,
            'X-User-Id': user_id,
            'X-Role': roles,
        }

        return headers

    def __call__(self, environ, start_response):
        try:
            self.log.debug('path_info: %s' % environ['PATH_INFO'])
            account = environ['PATH_INFO'].lstrip('/').split('/', 1)[0]
            self.log.debug('account: %s' % account)
        except IndexError:
            self.log.debug('Unable to pull account from request path')
            return HTTPNotFound()(environ, start_response)
        try:
            token = environ['HTTP_X_AUTH_TOKEN']
        except KeyError:
            self.log.debug('Unable to pull token from request headers')
            return HTTPUnauthorized()(environ, start_response)
        try:
            self.log.debug('Validate token')
            token_info = self.get_token_info(token, account)
        except InvalidUserToken, e:
            self.log.info('Invalid token (%s)' % e)
            return HTTPUnauthorized()(environ, start_response)
        except Exception:
            self.log.exception('Unable to validate token')
            return HTTPServiceUnavailable()(environ, start_response)
        self.log.info('Token valid')
        headers = self.get_headers(token_info)
        self.log.debug('adding headers -> %r' % headers)
        for header, value in headers.items():
            environ['HTTP_' + header.upper().replace('-', '_')] = value
        return self.app(environ, start_response)

    def cache_get(self, key):
        try:
            return self.redis.get(key)
        except redis.RedisError, e:
            self.log.error("Redis Error: %s" % e)
            return None

    def cache_set(self, key, value, expire=None):
        try:
            return self.redis.set(key, value, ex=expire)
        except redis.RedisError, e:
            self.log.error("Redis Error: %s" % e)
            return None


def filter_factory(global_conf, **local_conf):
    """Returns a callable that returns a piece of WSGI middleware."""

    def auth_filter(app):
        return RackAuth(local_conf, app)

    return auth_filter
