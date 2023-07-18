import datetime
import dotenv
import falcon
import hooks
import json
import logging
import os
import random
import requests
import util

# https://docs.gunicorn.org/en/latest/run.html#gunicorn
# run with `gunicorn -c hooks.py -b 0.0.0.0 "vrc:create_app()"`

default_library = None
status_list = []
current_queue = []
song_history = []

program_savestate_filename = None

ignore_events = False


def save_program_state():
    sstate = {'status_list': status_list, 'current_queue': current_queue, 'song_history': song_history}
    global program_savestate_filename
    with open(program_savestate_filename, 'w') as sfile:
        json.dump(sstate, sfile)


def evaluate_initial_state():
    global default_library, current_queue
    logger = logging.getLogger('vrc')

    state = player_get_state()
    # Example state: {'status': 'stop', 'position': 0, 'title': '', 'artist': '', 'album': '', 'albumart': '/albumart', 'duration': 0, 'uri': '', 'seek': 0, 'samplerate': '', 'channels': '', 'bitdepth': '', 'Streaming': False, 'service': 'mpd', 'volume': 41, 'dbVolume': None, 'mute': False, 'disableVolumeControl': False, 'random': None, 'repeat': None, 'repeatSingle': False, 'updatedb': False, 'consume': False}
    logger.debug(f'initial player state: {state}')

    queue = player_get_queue()
    # Example queue: []
    if len(current_queue) > 0:
        logger.error(f'evaluate_initial_state: current_queue not empty: {current_queue}')
    for song in queue:
        title = song['title'] if 'title' in song else song['name']
        s = {'title': title}
        s['artist'] = song['artist']
        s['uri'] = song['uri']
        current_queue.append(s)
    logger.debug(f'initial player queue: {current_queue}')

    if len(queue) == 0:
        play_random_song()


def play_random_song():
    logger = logging.getLogger('vrc')
    if len(default_library) > 0:
        song = default_library.pop(random.randrange(len(default_library)))
        logger.debug(f'play random song: {song}')
        player_replace_and_play(song)
    else:
        logger.warning('cannot play random song, library is empty')


def get_song_with_index(uri, song_list):
    for i, song in enumerate(song_list):
        if song['uri'] == uri:
            return song, i
    return None, None

def remove_song_from_both_queues(uri, request_play=True):
    # remove song from player queue
    player_remove_uri_from_queue(uri, request_play)
    # remove song from current_queue storage
    global current_queue
    song, index = get_song_with_index(uri, current_queue)
    if index is not None:
        del current_queue[index]


# https://falcon.readthedocs.io/en/stable/api/hooks.html#after-hooks
def evaluate_status(req, resp, resource):
    logger = logging.getLogger('vrc')
    global status_list, current_queue, song_history
    if len(status_list) == 0:
        return
    media = status_list.pop()
    logger.debug(f'evaluate_status: {media}')
    if len(status_list) > 0:
        logger.warning(f'status_list not empty ({len(status_list)} items remaining)! {status_list}')
    event = media['item']
    data = media['data']
    if event == 'state':
        if len(data['uri']) != 0:
            logger.info(f'{data["status"]}: {data["artist"]} - {data["title"]} ({data["uri"]})')
            if data['status'] == 'play':
                if len(song_history) == 0 or song_history[-1]['uri'] != data['uri']:
                        song_history.append({k: data[k] for k in ['artist', 'title', 'uri']})
                        save_program_state()
            if data['status'] == 'stop':
                if 'position' in data:
                    pos = data['position']
                    if pos == 0 and len(song_history) > 0:
                        hist_uri = song_history[-1]['uri']
                        uri = data['uri']
                        if uri != hist_uri:
                            logger.warning(f'uri mismatch: song_history[-1]["uri"] == {hist_uri}')
                        remove_song_from_both_queues(uri, request_play=False)
                        save_program_state()
                    else:
                        # Special case: A song has finished and another one is waiting in the queue. Volumio then emits
                        # a 'stop' event for the waiting song (position 1) instead of for the finished one (position 0).
                        for p in range(pos):
                            uri = song_history[-1 - p]['uri']
                            #play = (p == pos - 1)
                            remove_song_from_both_queues(uri, request_play=False)
                            save_program_state()
                else:
                    hist_uri = song_history[-1]['uri']
                    uri = data['uri']
                    if uri != hist_uri:
                        logger.warning(f'uri mismatch: song_history[-1]["uri"] == {hist_uri}')
                    remove_song_from_both_queues(uri, request_play=False)
                    save_program_state()
                if len(current_queue) == 0:
                    play_random_song()
    elif event == 'queue':
        changed = False
        queue = []
        for song in data:
            title = song['title'] if 'title' in song else song['name']
            s = {'title': title}
            s['artist'] = song['artist']
            s['uri'] = song['uri']
            queue.append(s)
        uris_old = {s['uri'] for s in current_queue}
        uris_new = {s['uri'] for s in queue}
        for uri in (uris_new - uris_old):
            song, i = get_song_with_index(uri, queue)
            if song is None:
                logger.error(f'uri not found in queue: {uri}')
            else:
                changed = True
                logger.info(f'song added to queue position {i}: {song["artist"]} - {song["title"]} ({song["uri"]})')
        for uri in (uris_old - uris_new):
            song, i = get_song_with_index(uri, current_queue)
            if song is None:
                logger.error(f'uri not found in current_queue: {uri}')
            elif len(song_history) == 0 or uri != song_history[-1]['uri']:
                changed = True
                logger.info(f'song removed from queue position {i}: {song["artist"]} - {song["title"]} ({song["uri"]})')
        if changed:
            current_queue = list(queue)
            save_program_state()
            player_state = player_get_state()
            logger.debug(f'queue changed, this is the current player state: {player_state}')
            if len(current_queue) == 0 and player_state['status'] == 'stop':
                play_random_song()


# TODO If stop and queue not empty --> request play

def player_remove_uri_from_queue(uri, request_play):
    logger = logging.getLogger('vrc')
    logger.debug(f'remove_uri_from_queue: {uri}')

    # find currently playing song in queue
    queue = player_get_queue()
    song, index = get_song_with_index(uri, queue)
    if index is not None:
        # deactivate the volumio notifications to prevent recursion
        global ignore_events, current_queue
        ignore_events = True
        #hooks.register_with_volumio(register=False)

        logger.debug(f'remove song from queue position {index}: {song["artist"]} - {song["name"]} ({song["uri"]})')
        del queue[index]

        logger.debug(f'clear queue')
        player_clear_queue()

        if len(queue) > 0:
            logger.debug(f'populate the queue with the remaining elements: {queue}')
            player_add_to_queue([{"uri": song['uri']} for song in queue])
            # Start playing the queue
            if request_play:
                player_cmd_play()

        # reactivate the volumio notifications
        #hooks.register_with_volumio()
        ignore_events = False


# https://developers.volumio.com/api/rest-api#music-library
# https://developers.volumio.com/api/rest-api#adding-items-to-playback
def player_get_state():
    logger = logging.getLogger('vrc')
    req = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/getState'
    logger.debug(f'requesting: {req}')
    return requests.get(req).json()


def player_get_queue():
    logger = logging.getLogger('vrc')
    req = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/getQueue'
    logger.debug(f'requesting: {req}')
    return requests.get(req).json()['queue']


def player_clear_queue():
    logger = logging.getLogger('vrc')
    req = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/commands/?cmd=clearQueue'
    logger.debug(f'requesting: {req}')
    requests.get(req)


def player_add_to_queue(queue):
    logger = logging.getLogger('vrc')
    req = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/addToQueue'
    logger.debug(f'requesting: {req} <-- {queue}')
    requests.post(req, json=queue)
    #for song in queue:
    #    requests.post(req_post_add_to_queue, json={"uri": song["uri"]})


def player_replace_and_play(song):
    logger = logging.getLogger('vrc')
    req = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/replaceAndPlay'
    logger.debug(f'requesting: {req} <-- {song}')
    requests.post(req, json=song)


def player_cmd_play(song_index=0):
    logger = logging.getLogger('vrc')
    req = f'http://{os.environ["VRC_VOLUMIO_HOST"]}/api/v1/commands/?cmd=play&N={song_index}'
    logger.debug(f'requesting: {req}')
    requests.get(req)


class VolumioStatus:

    @falcon.after(evaluate_status)
    def on_post(self, req, resp):
        # https://falcon.readthedocs.io/en/stable/api/request_and_response_wsgi.html#falcon.Request.get_media
        # https://developers.volumio.com/api/rest-api
        media = req.get_media()
        logger = logging.getLogger('vrc')
        global ignore_events
        if ignore_events:
            logger.debug(f'[EVENT IGNORED] /volumiostatus --> on_post: {media}')
        else:
            logger.debug(f'/volumiostatus --> on_post: {media}')
            global status_list
            status_list.append(media)
        resp.status = falcon.HTTP_200


def create_app():
    dotenv.load_dotenv()
    util.setup_logger()
    logger = logging.getLogger('vrc')
    logger.debug('vrc starting')

    #qfilename = './queue.json'
    qfilename = './queue_short.json'
    with open(qfilename, 'r') as queuefile:
        queue = json.load(queuefile)['queue']
        global default_library
        default_library = [{
            "name": song["name"],
            "artist": song["artist"],
            "uri": song["uri"],
        } for song in queue]
    global program_savestate_filename
    program_savestate_filename = f'{datetime.datetime.now().isoformat().replace(":", "-")}.savestate.json'
    evaluate_initial_state()

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
