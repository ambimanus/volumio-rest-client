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
status_list = []
current_queue = []
song_history = []


def get_song_with_index(uri, song_list):
    for i, song in enumerate(song_list):
        if song['uri'] == uri:
            return song, i
    return None, None


# https://falcon.readthedocs.io/en/stable/api/hooks.html#after-hooks
def evaluate_status(req, resp, resource):
    logger = logging.getLogger('vrc')
    global status_list, current_queue, song_history
    if len(status_list) == 0:
        return
    media = status_list.pop()
    logger.debug(f'evaluate_status: {media}')
    if len(status_list) > 0:
        logger.debug(f'status_list not empty ({len(status_list)} items remaining)! {status_list}')
    event = media['item']
    data = media['data']
    if event == 'state':
        logger.info(f'{data["status"]}: {data["artist"]} - {data["title"]} ({data["uri"]})')
        #status_list.append({'item': event, 'data': {k: data[k] for k in ['status', 'artist', 'title', 'uri']}})
        if len(song_history) == 0 or song_history[-1]['uri'] != data['uri']:
            song_history.append({k: data[k] for k in ['artist', 'title', 'uri']})
            remove_uri_from_queue(data['uri'])
    elif event == 'queue':
        queue = []
        for song in data:
            title = song['title'] if 'title' in song else song['name']
            s = {'title': title}
            s['artist'] = song['artist']
            s['uri'] = song['uri']
            queue.append(s)
        #status_list.append({'item': event, 'data': queue})
        uris_old = {s['uri'] for s in current_queue}
        uris_new = {s['uri'] for s in queue}
        for uri in (uris_new - uris_old):
            song, i = get_song_with_index(uri, queue)
            if song is None:
                logger.error(f'uri not found in queue: {uri}')
            else:
                logger.info(f'song added to queue position {i}: {song["artist"]} - {song["title"]} ({song["uri"]})')
        for uri in (uris_old - uris_new):
            song, i = get_song_with_index(uri, current_queue)
            if song is None:
                logger.error(f'uri not found in current_queue: {uri}')
            elif len(song_history) == 0 or uri != song_history[-1]['uri']:
                logger.info(f'song removed from queue position {i}: {song["artist"]} - {song["title"]} ({song["uri"]})')
        current_queue = list(queue)

    # TODO play random song from default_library


def remove_uri_from_queue(uri):
    logger = logging.getLogger('vrc')
    logger.debug(f'remove_uri_from_queue: {uri}')
    volumio_host = f'http://{os.environ["VRC_VOLUMIO_HOST"]}'

    # https://developers.volumio.com/api/rest-api#music-library
    # https://developers.volumio.com/api/rest-api#adding-items-to-playback
    # find currently playing song in queue
    req_get_queue = f'{volumio_host}/api/v1/getQueue'
    queue = requests.get(req_get_queue).json()['queue']
    song, index = get_song_with_index(uri, queue)
    if index is not None:
        # deactivate the volumio notifications to prevent recursion
        hooks.register_with_volumio(register=False)

        logger.debug(f'remove song from queue position {index}: {song["artist"]} - {song["name"]} ({song["uri"]})')
        del queue[index]

        logger.debug('clear queue')
        req_get_clear_queue = f'{volumio_host}/api/v1/commands/?cmd=clearQueue'
        requests.get(req_get_clear_queue)

        logger.debug(f'populate the queue with the remaining elements: {queue}')
        req_post_add_to_queue = f'{volumio_host}/api/v1/addToQueue'
        #for song in queue:
        #    requests.post(req_post_add_to_queue, json={"uri": song["uri"]})
        #data = f'{{"url":"{cb_url}"}}'
        requests.post(req_post_add_to_queue, json=[{"uri": song['uri']} for song in queue])

        # reactivate the volumio notifications
        hooks.register_with_volumio()


def get_player_state():
    logger = logging.getLogger('vrc')
    volumio_host = f'http://{os.environ["VRC_VOLUMIO_HOST"]}'
    req_get_state = f'{volumio_host}/api/v1/getState'
    return requests.get(req_get_state).json()


class VolumioStatus:

    @falcon.after(evaluate_status)
    def on_post(self, req, resp):
        # https://falcon.readthedocs.io/en/stable/api/request_and_response_wsgi.html#falcon.Request.get_media
        # https://developers.volumio.com/api/rest-api
        media = req.get_media()
        logger = logging.getLogger('vrc')
        logger.debug(f'/volumiostatus --> on_post: {media}')
        global status_list
        status_list.append(media)
        resp.status = falcon.HTTP_200


def create_app():
    dotenv.load_dotenv()
    util.setup_logger()
    logger = logging.getLogger('vrc')
    logger.debug('vrc starting')
    logger.debug(f'initial player state: {get_player_state()}')
    with open('./queue.json', 'r') as queuefile:
        queue = json.load(queuefile)['queue']
        global default_library
        default_library = [{
            "name": song["name"],
            "artist": song["artist"],
            "uri": song["uri"],
        } for song in queue]
    app = falcon.App()
    app.add_route('/volumiostatus', VolumioStatus())
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
