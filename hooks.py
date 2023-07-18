import dotenv
import json
import logging
import os
import requests
import util

def register_with_volumio(register=True):
    dotenv.load_dotenv()
    util.setup_logger()
    # https://developers.volumio.com/api/rest-api#notifications
    vol_url = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/pushNotificationUrls'
    cb_url = f'http://{os.environ["VRC_CALLBACK_HOST"]}/volumiostatus'
    method = 'POST' if register else 'DELETE'
    data = f'{{"url":"{cb_url}"}}'
    logger = logging.getLogger('vrc')
    logger.debug(f'register_with_volumio: request({method}, {vol_url}, json={json.loads(data)})')
    res = requests.request(method, vol_url, json=json.loads(data))
    # sanity check
    if (cb_url in json.loads(requests.get(vol_url).text)) != register:
        logger.error('register_with_volumio: request failed')

def when_ready(server):
    register_with_volumio()

def on_exit(server):
    register_with_volumio(register=False)


if __name__ == '__main__':
    register_with_volumio(register=False)
