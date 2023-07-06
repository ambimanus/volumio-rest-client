import dotenv
import json
import os
import requests

def register_with_volumio(unregister=False):
    dotenv.load_dotenv()
    # https://developers.volumio.com/api/rest-api#notifications
    vol_url = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/pushNotificationUrls'
    cb_url = f'http://{os.environ["VRC_CALLBACK_HOST"]}/volumiostatus'
    method = 'DELETE' if unregister else 'POST'
    data = f'{{"url":"{cb_url}"}}'
    res = requests.request(method, vol_url, json=json.loads(data))
    # sanity check
    assert (cb_url in json.loads(requests.get(vol_url).text)) != unregister

def when_ready(server):
    register_with_volumio()

def on_exit(server):
    register_with_volumio(unregister=True)


if __name__ == '__main__':
    register_with_volumio(unregister=True)