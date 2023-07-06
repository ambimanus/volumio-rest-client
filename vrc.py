import dotenv
import falcon
import hooks
import json
import logging
import os
import requests
import util

# https://docs.gunicorn.org/en/latest/run.html#gunicorn
# run with `gunicorn -c hooks.py -b 0.0.0.0 "vrc:create_app()"`

default_library = None

# https://falcon.readthedocs.io/en/stable/api/hooks.html#after-hooks
def update_queue(req, resp, resource):
    # deactivate the volumio notifications to prevent recursion
    hooks.register_with_volumio(unregister=True)

    # check if we should run
    media = req.get_media()
    if media['item'] != 'state' and media['data']['status'] != 'play':
        return

    req_host = f'http://{os.environ["VRC_VOLUMIO_HOST"]}'
    # https://developers.volumio.com/api/rest-api#music-library
    # https://developers.volumio.com/api/rest-api#adding-items-to-playback
    # find currently playing song in queue
    song_uri = media['data']['uri']
    req_get_queue = f'{req_host}/api/v1/getQueue'
    queue = requests.get(req_get_queue).json()['queue']
    index = None
    for i, song in enumerate(queue):
        if song['uri'] == song_uri:
            index = i
            break
    if index is not None:
        logger = logging.getLogger('vrc')
        logger.debug(f'remove song from queue position {index}: {song["artist"]} - {song["name"]} ({song["uri"]})')
        del queue[index]

    # clear queue
    req_get_clear_queue = f'{req_host}/api/v1/commands/?cmd=clearQueue'
    requests.get(req_get_clear_queue)

    # populate the queue with the remaining elements
    req_post_add_to_queue = f'{req_host}/api/v1/addToQueue'
    requests.post(req_post_add_to_queue, json={"uri": song['uri'] for song in queue})

    # reactivate the volumio notifications
    hooks.register_with_volumio(unregister=True)


class StatusReceiver:

    @falcon.after(update_queue)
    def on_post(self, req, resp):
        # https://falcon.readthedocs.io/en/stable/api/request_and_response_wsgi.html#falcon.Request.get_media
        media = req.get_media()
        reason = media['item']
        data = media['data']
        logger = logging.getLogger('vrc')
        if reason == 'state' and data['status'] == 'play':
            logger.info(f'now playing: {data["artist"]} - {data["title"]} ({data["uri"]})')
        elif reason == 'queue':
            queue = [f'{song["artist"]} - {song["title"]} ({song["uri"]})' for song in data]
            logger.info(f'queue updated: {queue})')
        resp.status = falcon.HTTP_200


def create_app():
    with open('./queue.json', 'r') as queuefile:
        queue = json.load(queuefile)['queue']
        global default_library
        default_library = [{
            "name": song["name"],
            "artist": song["artist"],
            "uri": song["uri"],
        } for song in queue]
    dotenv.load_dotenv()
    util.setup_logger()
    app = falcon.App()
    app.add_route('/volumiostatus', StatusReceiver())
    return app


if __name__ == '__main__':

    class Mock:
        def get_media(self):
            queue = """
            {"queue": [{"uri": "spotify:track:4eRmCZWJoEtLl0wy7EJPwd", "service": "spop", "name": "Dickes B (feat. Black Kappa)", "artist": "Seeed", "album": "New Dubby Conquerors", "type": "song", "duration": 284, "albumart": "https://i.scdn.co/image/ab67616d0000b27389917cfa3391d5c872396e6f", "samplerate": "160 kbps", "bitdepth": "16 bit", "bitrate": "", "trackType": "spotify"}, {"uri": "spotify:track:6b2vkaiDawOcupyDxNNCba", "service": "spop", "name": "Dancehall Caballeros", "artist": "Seeed", "album": "New Dubby Conquerors", "type": "song", "duration": 192, "albumart": "https://i.scdn.co/image/ab67616d0000b27389917cfa3391d5c872396e6f", "samplerate": "160 kbps", "bitdepth": "16 bit", "bitrate": "", "trackType": "spotify"}, {"uri": "spotify:track:7A4KdLy1DXOOC5fhIdDuHz", "service": "spop", "name": "Haus am See", "artist": "Peter Fox", "album": "Stadtaffe", "type": "song", "duration": 216, "albumart": "https://i.scdn.co/image/ab67616d0000b2739061a4e47413aff8f58a3c9c", "samplerate": "160 kbps", "bitdepth": "16 bit", "bitrate": "", "trackType": "spotify"}, {"uri": "spotify:track:1ooatRQWNtl4jB7hQoanFz", "service": "spop", "name": "Riddim No 1", "artist": "Seeed", "album": "New Dubby Conquerors", "type": "song", "duration": 233, "albumart": "https://i.scdn.co/image/ab67616d0000b27389917cfa3391d5c872396e6f", "samplerate": "160 kbps", "bitdepth": "16 bit", "bitrate": "", "trackType": "spotify"}, {"uri": "spotify:track:0c4IEciLCDdXEhhKxj4ThA", "service": "spop", "name": "Madness", "artist": "Muse", "album": "The 2nd Law", "type": "song", "duration": 281, "albumart": "https://i.scdn.co/image/ab67616d0000b273fc192c54d1823a04ffb6c8c9", "samplerate": "160 kbps", "bitdepth": "16 bit", "bitrate": "", "trackType": "spotify"}]}
            """
            state = """
            {"item": "state", "data": {"status": "play", "title": "Dancehall Caballeros", "artist": "Seeed", "album": "New Dubby Conquerors", "albumart": "https://i.scdn.co/image/ab67616d0000b27389917cfa3391d5c872396e6f", "uri": "spotify:track:6b2vkaiDawOcupyDxNNCba", "trackType": "spotify", "seek": 187683, "duration": 193, "samplerate": "160 kbps", "bitdepth": "16 bit", "channels": 2, "consume": false, "volume": 8, "dbVolume": "", "mute": false, "disableVolumeControl": false, "stream": false, "updatedb": false, "volatile": true, "service": "spop"}}
            """
            return json.loads(state)

    dotenv.load_dotenv()
    # test update_queue
    update_queue(Mock(), None, None, None)
