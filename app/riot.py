from __future__ import annotations

import os
from urllib.parse import quote

import httpx


class RiotApiError(ValueError):
    pass


async def lookup_kr_player(riot_id: str) -> dict:
    api_key = os.getenv("RIOT_API_KEY", "").strip()
    if not api_key:
        raise RiotApiError("RIOT_API_KEY가 설정되지 않았습니다.")
    if "#" not in riot_id:
        raise RiotApiError("Riot ID를 게임이름#태그 형식으로 입력해 주세요.")

    game_name, tag_line = [part.strip() for part in riot_id.rsplit("#", 1)]
    headers = {"X-Riot-Token": api_key}
    timeout = httpx.Timeout(10)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        account_url = (
            "https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
            f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
        )
        account_response = await client.get(account_url)
        if account_response.status_code == 404:
            raise RiotApiError("해당 Riot ID를 찾지 못했습니다.")
        if account_response.status_code != 200:
            raise RiotApiError(
                f"Riot API 계정 조회 실패 ({account_response.status_code})"
            )
        account = account_response.json()
        puuid = account["puuid"]

        league_response = await client.get(
            f"https://kr.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        )
        summoner_response = await client.get(
            f"https://kr.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        )
        entries = league_response.json() if league_response.status_code == 200 else []
        solo = next(
            (entry for entry in entries if entry["queueType"] == "RANKED_SOLO_5x5"),
            None,
        )
        tier = "UNRANKED"
        if solo:
            tier = f'{solo["tier"]} {solo["rank"]} · {solo["leaguePoints"]} LP'

        profile_icon_url = None
        if summoner_response.status_code == 200:
            icon_id = summoner_response.json().get("profileIconId")
            if icon_id is not None:
                profile_icon_url = (
                    "https://ddragon.leagueoflegends.com/cdn/16.12.1/"
                    f"img/profileicon/{icon_id}.png"
                )

        champions: dict[str, dict] = {}
        match_ids_response = await client.get(
            "https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/"
            f"{puuid}/ids",
            params={"start": 0, "count": 8},
        )
        match_ids = match_ids_response.json() if match_ids_response.status_code == 200 else []
        for match_id in match_ids:
            match_response = await client.get(
                f"https://asia.api.riotgames.com/lol/match/v5/matches/{match_id}"
            )
            if match_response.status_code != 200:
                continue
            participants = match_response.json().get("info", {}).get("participants", [])
            participant = next(
                (item for item in participants if item.get("puuid") == puuid),
                None,
            )
            if not participant:
                continue
            champion_name = participant.get("championName") or "Unknown"
            champion = champions.setdefault(
                champion_name,
                {
                    "name": champion_name,
                    "games": 0,
                    "wins": 0,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                },
            )
            champion["games"] += 1
            champion["wins"] += 1 if participant.get("win") else 0
            champion["kills"] += int(participant.get("kills") or 0)
            champion["deaths"] += int(participant.get("deaths") or 0)
            champion["assists"] += int(participant.get("assists") or 0)

    return {
        "name": f"{account.get('gameName', game_name)}#{account.get('tagLine', tag_line)}",
        "riot_id": f"{account.get('gameName', game_name)}#{account.get('tagLine', tag_line)}",
        "tier": tier,
        "profile_icon_url": profile_icon_url,
        "champions": sorted(
            champions.values(),
            key=lambda item: (-item["games"], -item["wins"], item["name"]),
        ),
    }

