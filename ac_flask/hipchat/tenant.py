from datetime import timedelta
import time
from .db import db
import jwt
import logging
import requests
from requests.auth import HTTPBasicAuth
from werkzeug.exceptions import abort

_log = logging.getLogger(__name__)

ACCESS_TOKEN_CACHE = "hipchat-tokens:{oauth_id}"


class Tenant:

    def __init__(self, id, secret=None, homepage=None, capabilities_url=None, room_id=None, token_url=None,
                 group_id=None, group_name=None, capdoc=None):
        self.id = id
        self.room_id = room_id
        self.secret = secret
        self.group_id = group_id
        self.group_name = None if not group_name else group_name
        self.homepage = homepage or None if not capdoc else capdoc['links']['homepage']
        self.token_url = token_url or None if not capdoc else capdoc['capabilities']['oauth2Provider']['tokenUrl']
        self.capabilities_url = capabilities_url or None if not capdoc else capdoc['links']['self']

    def to_map(self):
        return {
            "id": self.id,
            "secret": self.secret,
            "room_id": self.room_id,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "homepage": self.homepage,
            "token_url": self.token_url,
            "capabilities_url": self.capabilities_url
        }

    @staticmethod
    def from_map(data):
        filtered = {key: val for key, val in data.items() if not key.startswith('_')}
        return Tenant(**filtered)

    @staticmethod
    def load(client_id):
        client_data = db.get(client_id)
        if client_data:
            return Tenant.from_map(client_data)
        else:
            _log.warn("Cannot find client: %s" % client_id)
            abort(400)

    @property
    def id_query(self):
        return {"id": self.id}

    def get_token(self, token_only=True, scopes=None):
        if scopes is None:
            scopes = ["send_notification"]

        cache_key = ACCESS_TOKEN_CACHE.format(oauth_id=self.id)
        cache_key += ":" + ",".join(scopes)

        def gen_token():
            resp = requests.post(self.token_url, data={"grant_type": "client_credentials", "scope": " ".join(scopes)},
                                 auth=HTTPBasicAuth(self.id, self.secret), timeout=10)
            if resp.status_code == 200:
                _log.debug("Token request response: " + resp.text)
                return resp.json()
            elif resp.status_code == 401:
                _log.error("Client %s is invalid but we weren't notified.  Uninstalling" % self.id)
                raise OauthClientInvalidError(self)
            else:
                raise Exception("Invalid token: %s" % resp.text)

        if token_only:
            token = db.get(cache_key)
            if not token:
                data = gen_token()
                token = data['access_token']
                db[cache_key] = token
            return token
        else:
            return gen_token()

    def sign_jwt(self, user_id, data=None):
        if data is None:
            data = {}

        now = int(time.time())
        exp = now + timedelta(hours=1).total_seconds()

        jwt_data = {"iss": self.id,
                    "iat": now,
                    "exp": exp}

        if user_id:
            jwt_data['prn'] = user_id

        data.update(jwt_data)
        return jwt.encode(data, self.secret)


class OauthClientInvalidError(Exception):
    def __init__(self, client, *args, **kwargs):
        super(OauthClientInvalidError, self).__init__(*args, **kwargs)
        self.client = client
