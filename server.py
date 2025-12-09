import json
import string
import random
import urllib.parse
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote

from sortable_column import SortableColumn
from nicegui import ui, app
import requests
import mysql.connector

status = {
    10: "Unplayed",
    20: "Unfinished",
    30: "Beaten",
    40: "Completed",
    50: "Endless",
    60: "None",
}

priority = {
    10: "Shelved",
    20: "Replay",
    30: "Low",
    40: "Normal",
    50: "High",
    60: "Paused",
    70: "Ongoing",
    80: "Playing",
}


def on_change(ni, oi):
    # ui.notify(f'Moved "{app.storage.client["games"][oi]["title"]}" to position {ni + 1}')
    app.storage.client["games"].insert(ni, app.storage.client["games"].pop(oi))


def get_cred(cred: str):
    with open("creds.json") as f:
        keys = json.load(f)[0]
        block, item = cred.split("→")
        return keys[block][item] if block in keys and item in keys[block] else ""


def send_games_to_db(games):
    game_poller_db = mysql.connector.connect(
        host=get_cred("db→host"),
        user=get_cred("db→user"),
        password=get_cred("db→password"),
        database=get_cred("db→database"),
    )

    cursor = game_poller_db.cursor()

    user_id = app.storage.browser["twitch_user"]

    sql = ("INSERT INTO votes (twitch_user, game, score) VALUES (%s, %s, %s) "
           "ON DUPLICATE KEY UPDATE twitch_user = VALUES(twitch_user), game = VALUES(game), score = VALUES(score)")
    values = [
        (user_id, game["game_inst_id"], len(games) - i) for i, game in enumerate(games)
    ]

    cursor.executemany(sql, values)

    game_poller_db.commit()

    ui.notify("Thank you for your ranking!", position="top")
    display_ranking.refresh()


def get_game_ranking() -> list[
    tuple[Decimal | bytes | date | datetime | float | int | set[str] | str | timedelta | None | time, ...] | dict[
        str, Decimal | bytes | date | datetime | float | int | set[str] | str | timedelta | None | time]]:
    game_poller_db = mysql.connector.connect(
        host=get_cred("db→host"),
        user=get_cred("db→user"),
        password=get_cred("db→password"),
        database=get_cred("db→database"),
    )

    cursor = game_poller_db.cursor()

    cursor.execute("SELECT game, SUM(score) AS total_score FROM votes GROUP BY game ORDER BY total_score DESC")


    return cursor.fetchall()


def get_twitch_auth_url() -> str:
    app.storage.browser["twitch_state"] = ''.join(
        random.SystemRandom().choice(string.ascii_lowercase + string.digits) for _ in range(20))
    return (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={get_cred("twitch→client_id")}"
        f"&redirect_uri={urllib.parse.quote(get_cred("twitch→redirect_uri"))}"
        f"&scope="
        f"&state={app.storage.browser['twitch_state']}"
    )


def submit_games():
    if app.storage.client["games"]:
        # Validate Twitch token first
        validation_headers = {"Authorization": f"OAuth {app.storage.browser['twitch_access_token']}"}
        validation_response = requests.get("https://id.twitch.tv/oauth2/validate", headers=validation_headers)

        if validation_response.status_code == 200:
            send_games_to_db(app.storage.client["games"])
        else:
            login_needed = False

            if validation_response.status_code == 401:
                ui.notify("Twitch token invalid. Attempting token refresh.", position="top")

                refresh_data = (
                    f"client_id={get_cred("twitch→client_id")}"
                    f"&client_secret={get_cred("twitch→client_secret")}"
                    "&grant_type=authorization_code"
                    f"&refresh_token={quote(app.storage.browser['twitch_refresh_token'])}")
                refresh_response = requests.post("https://id.twitch.tv/oauth2/token", data=refresh_data)

                if refresh_response.status_code == 200:
                    r = refresh_response.json()
                    app.storage.browser["twitch_access_token"] = r["access_token"]
                    app.storage.browser["twitch_refresh_token"] = r["refresh_token"]
                    ui.notify("Refresh successful. Submitting ranking...", position="top")
                    send_games_to_db(app.storage.client["games"])
                else:
                    ui.notify("Refresh failed. Please login again.", position="top")
                    login_needed = True
            else:
                login_needed = True

            if login_needed:
                with ui.dialog() as _dialog, ui.card():
                    ui.label("Something went wrong with your Twitch connection.")
                    full_url = get_twitch_auth_url()
                    ui.button("Log in with Twitch", on_click=lambda: ui.navigate.to(full_url))
    else:
        ui.notify("No games found. This.... this shouldn't be possible. What. How did you do that.")


@ui.page("/game_poller")
def game_poller():
    url = "https://backloggery.com/api/fetch_library.php"
    obj = {"type": "load_user_library", "username": get_cred("backloggery→user")}
    response = requests.post(url, json=obj)
    if response.status_code != 200:
        ui.label("Oops. Connection to Backloggery did NOT work. Response received:")
        ui.label(response.text)
    else:
        games = [x for x in sorted(response.json(), key=lambda x: x["title"]) if x["priority"] not in [10, 60]]

        # with open("games.json") as f:
        #     games = [x for x in sorted(json.load(f), key=lambda x: x["title"]) if x["priority"] not in [10, 60]]
        games_by_id = {}
        for game in games:
            games_by_id[str(game["game_inst_id"])] = game

        app.storage.client["games"] = games

        with ui.row().classes("w-full justify-end gap-40"):
            login_needed = False

            if 'twitch_access_token' not in app.storage.browser:
                login_needed = True
            else:
                validation_headers = {"Authorization": f"OAuth {app.storage.browser['twitch_access_token']}"}
                validation_response = requests.get("https://id.twitch.tv/oauth2/validate", headers=validation_headers)
                if validation_response.status_code == 200:
                    with ui.column().classes("w-2/3 items-center"):
                        with ui.row().classes("w-full max-w-xl justify-between"):
                            ui.label("Which game should I play next?").classes("text-xl")
                            ui.button("Submit ranking", on_click=submit_games).props("color=teal-600").classes("text-right")

                        ui.label("Drag these around in your preferred order then click ↑ SUBMIT ↑").classes("w-full max-w-xl text-sm text-slate-500 text-right")

                        with SortableColumn(on_change=on_change, group='test').classes("bg-teal-600 items-stretch p-8 max-w-xl"):
                            for game in games:
                                with ui.card().classes("cursor-grab"):
                                    with ui.column().classes("w-full gap-0"):
                                        ui.label(game['title']).classes("text-lg")
                                        with ui.label(game['notes']).classes("w-full line-clamp-1 text-xs text-slate-500 text-right"):
                                            ui.tooltip(game['notes'])
                else:
                    login_needed = True

            if login_needed:
                full_url = get_twitch_auth_url()
                with ui.column().classes("grow items-center"):
                    ui.button("Log in with Twitch to cast your votes", on_click=lambda: ui.navigate.to(full_url)).props("color=purple-800")

            display_ranking(games_by_id)

@ui.refreshable
def display_ranking(games: dict):
    with ui.column().classes(""):
        ui.label("Current ranking").classes("text-lg")

        ranking = get_game_ranking()
        with ui.list():
            for game in ranking:
                ui.label(games[game[0]]["title"])


@ui.page("/twitch_callback/")
def twitch_callback(state: str, code: str = "", error: str = "", error_description: str = ""):
    if state == app.storage.browser["twitch_state"]:
        if error:
            print("Login failed.")
            print(error_description)
        else:
            app.storage.browser["twitch_state"] = ""
            # app.storage.browser["twitch_code"] = code
            # app.storage.browser["twitch_scope"] = scope
            url = "https://id.twitch.tv/oauth2/token"
            body = (f"client_id={get_cred("twitch→client_id")}"
                    f"&client_secret={get_cred("twitch→client_secret")}"
                    f"&code={code}"
                    "&grant_type=authorization_code"
                    f"&redirect_uri={urllib.parse.quote(get_cred("twitch→redirect_uri"))}")

            response = requests.post(url, data=body)
            if response.status_code == 200:
                r = response.json()
                if r["access_token"]:
                    app.storage.browser["twitch_access_token"] = r["access_token"]
                    app.storage.browser["twitch_refresh_token"] = r["refresh_token"]
                    app.storage.browser["twitch_expiration"] = r["expires_in"]
                    ui.navigate.to(game_poller)

                    # Retrieve user ID
                    user_headers = {
                        "Authorization": f"Bearer {app.storage.browser['twitch_access_token']}",
                        "Client-ID": get_cred("twitch→client_id")
                    }
                    user_response = requests.get("https://api.twitch.tv/helix/users", headers=user_headers)

                    if user_response.status_code == 200:
                        app.storage.browser["twitch_user"] = user_response.json()["data"][0]["id"]
                    else:
                        if user_response.status_code == 400:
                            ui.html('<style>.multi-line-notification { white-space: pre-line; }</style>', sanitize=False)
                            ui.notification(
                                "Uhhh twitch machine borken. Couldn't retrieve your user ID. \n"
                                "Apparently this was because of a Bad Request. Let the admin know about it.",
                                timeout=None,
                                close_button=True,
                                multi_line=True,
                                classes='multi-line-notification'
                            )
                        elif user_response.status_code == 401:
                            ui.html('<style>.multi-line-notification { white-space: pre-line; }</style>', sanitize=False)
                            ui.notification(
                                "Uhhh twitch machine borken. Couldn't retrieve your user ID.\n"
                                "This was due to an Unauthorized response. Let the admin know about it.",
                                timeout=None,
                                close_button=True,
                                multi_line=True,
                                classes='multi-line-notification'
                            )
                        else:
                            ui.notification("how. you somehow managed to get an error code not in the doc. "
                                            "what did you do")


@ui.page("/")
def page():
    ui.label("hmmmmm no i don't think so")
    ui.navigate.to(game_poller)


ui.run(
    page,
    favicon="🕹",
    title="GAMES",
    storage_secret="whAt_the_fUck_ever_man_idec_anyumor3",
    port=int(get_cred("run→port")),
    ssl_certfile=get_cred("cert→ssl_certfile"),
    ssl_keyfile=get_cred("cert→ssl_keyfile"),
    show=False
)
