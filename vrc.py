import datetime
import dotenv
import json
import logging
import os
import random
import requests
import time
import util


SLEEP_DURATION_SECONDS = 1

default_library = None
last_player_state = {'status': '', 'uri': ''}
last_player_queue = []
song_history = []
last_removed_uri = None

program_savestate_filename = None


def save_program_state():
    sstate = {'last_player_state': last_player_state,
              'last_player_queue': last_player_queue,
              'song_history': song_history}
    global program_savestate_filename
    with open(program_savestate_filename, 'w') as sfile:
        json.dump(sstate, sfile)


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


def player_remove_uri_from_queue(uri):
    logger = logging.getLogger('vrc')
    logger.debug(f'remove_uri_from_queue: {uri}')

    # find currently playing song in queue
    queue = player_get_queue()
    song, index = get_song_with_index(uri, queue)
    if index is not None:
        logger.debug(f'remove song from queue position {index}: {song["artist"]} - {song["name"]} ({song["uri"]})')
        del queue[index]

        logger.debug(f'clear queue')
        player_clear_queue()

        if len(queue) > 0:
            logger.debug(f'populate the queue with the remaining elements: {queue}')
            player_add_to_queue([{"uri": song['uri']} for song in queue])


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


def evaluate_player_state():
    global last_player_state, last_player_queue, song_history, last_removed_uri
    logger = logging.getLogger('vrc')

    # UPDATE INTERNAL STATE

    player_state = player_get_state()
    # Example state: {'status': 'stop', 'position': 0, 'title': '', 'artist': '', 'album': '', 'albumart': '/albumart', 'duration': 0, 'uri': '', 'seek': 0, 'samplerate': '', 'channels': '', 'bitdepth': '', 'Streaming': False, 'service': 'mpd', 'volume': 41, 'dbVolume': None, 'mute': False, 'disableVolumeControl': False, 'random': None, 'repeat': None, 'repeatSingle': False, 'updatedb': False, 'consume': False}
    player_state = {k: player_state[k] for k in ['status', 'title', 'artist', 'uri']}
    # Shortened state: {'status': 'stop', 'title': '', 'artist': '', 'uri': ''}
    state_changed = (player_state['status'] != last_player_state['status'] or
                     player_state['uri'] != last_player_state['uri'])
    if state_changed:
        logger.info(f'player state changed: [{player_state["status"]}] {player_state["artist"]} - {player_state["title"]} ({player_state["uri"]})')
    if player_state['status'] == 'play' and (len(song_history) == 0 or song_history[-1]['uri'] != player_state['uri']):
        song_history.append(dict(player_state))

    queue_data = player_get_queue()
    # Example queue: [{'uri': 'spotify:track:5PUvinSo4MNqW7vmomGRS7', 'service': 'spop', 'title': 'Blurred Lines', 'artist': 'Robin Thicke', 'album': 'Blurred Lines', 'type': 'song', 'duration': 263, 'albumart': 'https://i.scdn.co/image/ab67616d0000b2733d74cd7e75846d10c68afd52', 'samplerate': '160 kbps', 'bitdepth': '16 bit', 'bitrate': '', 'trackType': 'spotify'}]
    queue_changed = False
    player_queue = []
    for song in queue_data:
        title = song['title'] if 'title' in song else song['name']
        s = {'title': title}
        s['artist'] = song['artist']
        s['uri'] = song['uri']
        player_queue.append(s)
    # Shortened queue: [{'uri': 'spotify:track:5PUvinSo4MNqW7vmomGRS7', 'title': 'Blurred Lines', 'artist': 'Robin Thicke'}]
    uris_old = {s['uri'] for s in last_player_queue}
    uris_new = {s['uri'] for s in player_queue}
    # Loop over removed songs
    for uri in (uris_old - uris_new):
        song, i = get_song_with_index(uri, last_player_queue)
        if song is None:
            logger.error(f'uri not found in last_player_queue: {uri}')
        else:
            queue_changed = True
            logger.info(f'song removed from queue position {i}: {song["artist"]} - {song["title"]} ({song["uri"]})')
    # Loop over added songs
    for uri in (uris_new - uris_old):
        song, i = get_song_with_index(uri, player_queue)
        if song is None:
            logger.error(f'uri not found in player_queue: {uri}')
        else:
            queue_changed = True
            logger.info(f'song added to queue position {i}: {song["artist"]} - {song["title"]} ({song["uri"]})')

    # Store state to disk if something changed
    if state_changed or queue_changed:
        last_player_state = player_state
        last_player_queue = player_queue
        logger.debug(f'state or queue changed, saving program state')
        save_program_state()


    # TAKE ACTIONS
    # (will be reported in next loop)

    # Housekeeping: Remove last played song from first queue position
    if len(song_history) > 0:
        uri = song_history[-1]['uri']
        if last_player_state['status'] == 'stop' and len(last_player_queue) > 0:
            if uri == last_player_queue[0]['uri']:
                player_remove_uri_from_queue(uri)
                last_removed_uri = uri
        if last_player_state['status'] == 'play' and len(last_player_queue) > 1:
            if uri == last_player_queue[1]['uri']:
                player_remove_uri_from_queue(uri)
                last_removed_uri = uri

    # Check if the player is idle and if we should play a song
    if (not state_changed) and (not queue_changed) and (player_get_state()['status'] == 'stop'):
        # Play random song if queue is empty or if it only contains the previously played song
        if (len(last_player_queue) == 0) or (len(last_player_queue) == 1 and last_player_queue[0]['uri'] == last_removed_uri):
            play_random_song()
        # otherwise, play next song if queue is not empty
        elif len(last_player_queue) > 0:
            player_cmd_play()


def main():
    dotenv.load_dotenv()
    util.setup_logger()
    logger = logging.getLogger('vrc')
    logger.debug('vrc starting')

    qfilename = './queue.json'
    #qfilename = './queue_short.json'
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

    while True:
        evaluate_player_state()
        time.sleep(SLEEP_DURATION_SECONDS)


if __name__ == '__main__':
    main()