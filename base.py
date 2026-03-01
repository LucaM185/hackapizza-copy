# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "aiohttp",
#     "datapizza-ai",
#     "datapizza-ai-clients-openai-like"
# ]
# ///

import asyncio
import json
import random
from datetime import datetime
from typing import Any, Awaitable, Callable
from agenti import opener, bidder, menu, prepara, servi, notizie, strategia
from ricette import ricette as all_recipes

from src.config import TEAM_API_KEY, TEAM_ID
import aiohttp

TEAM_ID = 15  # your team id
TEAM_API_KEY = "dTpZhKpZ02-b91de4ab95c9fa33d6c7c9c0"

BASE_URL = "https://hackapizza.datapizza.tech"

if not TEAM_API_KEY or not TEAM_ID:
    raise SystemExit("Set TEAM_API_KEY and TEAM_ID")


def log(tag: str, message: str) -> None:
    print(f"[{tag}] {datetime.now()}: {message}")


# ── Serving state ────────────────────────────────────────────
current_turn_id: int = 0
pending_dishes: dict[str, list[str]] = {}  # dish_name -> [client_id, ...]
current_menu: list[str] = []
current_strategy: str | None = None  # "prestigio", "velocità", "prezzo"


async def game_started(data: dict[str, Any]) -> None:
    global current_turn_id, current_strategy
    current_turn_id = data.get("turn_id", 0)
    opener.run("Apri il ristorante")
    log("EVENT", "game started, turn id: " + str(current_turn_id))

    # ── Fetch bid history del turno precedente ──
    prev_turn = current_turn_id - 1
    if prev_turn > 0:
        try:
            import requests
            resp = requests.get(
                f"{BASE_URL}/bid_history",
                params={"turn_id": prev_turn},
                headers={"x-api-key": TEAM_API_KEY},
            )
            resp.raise_for_status()
            bids = resp.json()
            completed = [b for b in bids if b.get("status") == "COMPLETED"]
            log("BIDS", f"turno {prev_turn}: {len(completed)} bids COMPLETED su {len(bids)} totali")

            # Calcola min e media per ingrediente
            from collections import defaultdict
            prices: dict[str, list[float]] = defaultdict(list)
            for b in completed:
                ing_name = b.get("ingredient", {}).get("name", f"id_{b.get('ingredientId')}")
                prices[ing_name].append(b["priceForEach"])

            if prices:
                log("BIDS", f"{'Ingrediente':<35} {'Min':>6} {'Media':>8}")
                log("BIDS", "-" * 55)
                for ing in sorted(prices):
                    p = prices[ing]
                    log("BIDS", f"{ing:<35} {min(p):>6.1f} {sum(p)/len(p):>8.1f}")
            else:
                log("BIDS", "nessuna bid COMPLETED nel turno precedente")
        except Exception as e:
            log("ERROR", f"fetch bid_history failed: {e}")

    # ── Fetch notizie e classifica strategia ──
    try:
        log("STRATEGY", "fetching news for strategy classification...")
        news_result = notizie.run(
            "Fetch the content from https://hackablog.datapizza.tech/tag/news/ "
            "and return the titles and key content of the two most recent articles."
        )
        news_text = news_result.text if news_result else ""
        log("NEWS", f"news fetched: {news_text[:300]}...")

        if news_text:
            strat_result = strategia.run(
                f"Analizza queste notizie e dimmi la strategia:\n\n{news_text}"
            )
            raw = (strat_result.text or "").strip().lower()
            log("STRATEGY", f"raw LLM response: {raw!r}")

            if "prestigio" in raw:
                current_strategy = "prestigio"
            elif "velocit" in raw:
                current_strategy = "velocità"
            elif "prezzo" in raw:
                current_strategy = "prezzo"
            else:
                current_strategy = None
                log("STRATEGY", "could not classify, defaulting to None")

            log("STRATEGY", f"current_strategy = {current_strategy}")
        else:
            current_strategy = None
            log("STRATEGY", "no news text, defaulting to None")
    except Exception as e:
        current_strategy = None
        log("ERROR", f"strategy classification failed: {e}")

async def speaking_phase_started() -> None:
    log("EVENT", "speaking phase started (no-op, strategy handled in game_started)")


def get_inventory() -> dict:
    import requests
    url = f"{BASE_URL}/restaurants"
    log("DEBUG", f"get_inventory() calling GET {url}")
    try:
        response = requests.get(url, headers={"x-api-key": TEAM_API_KEY})
        log("DEBUG", f"get_inventory() status_code={response.status_code}")
        response.raise_for_status()
        restaurants = response.json()
        log("DEBUG", f"get_inventory() got {len(restaurants)} restaurants")
        for r in restaurants:
            r_id = r.get("id")
            r_name = r.get("name", "?")
            r_inv = r.get("inventory", {})
            log("DEBUG", f"  restaurant id={r_id} name={r_name!r} inventory_keys={list(r_inv.keys())[:5]}... ({len(r_inv)} items)")
            if str(r_id) == str(TEAM_ID):
                log("DEBUG", f"  >>> MATCH! team_id={TEAM_ID}, inventory has {len(r_inv)} items")
                if r_inv:
                    log("DEBUG", f"  >>> first 10 items: {dict(list(r_inv.items())[:10])}")
                else:
                    log("DEBUG", f"  >>> inventory is EMPTY! full restaurant data: {r}")
                return r_inv
        log("DEBUG", f"get_inventory() team_id={TEAM_ID} NOT FOUND in {[r.get('id') for r in restaurants]}")
        return {}
    except Exception as e:
        log("ERROR", f"get_inventory() failed: {e}")
        return {}


def print_inventory() -> None:
    inventory = get_inventory()
    if not inventory:
        log("INVENTORY", "inventario vuoto")
        return
    log("INVENTORY", f"{'Ingrediente':<40} Quantità")
    log("INVENTORY", "-" * 50)
    for ingredient, qty in sorted(inventory.items()):
        log("INVENTORY", f"{ingredient:<40} {qty}")


async def closed_bid_phase_started() -> None:
    from ingredienti import ingredienti
    log("BID", f"closed_bid phase started, placing bid for {len(ingredienti)} ingredients...")
    log("BID", f"ingredients list: {ingredienti}")
    prompt = "Fai un'offerta, compra due elementi di tutto a 3 euro ciascuno, " + str(ingredienti)
    log("BID", f"bidder prompt: {prompt[:200]}...")
    for attempt in range(3):
        try:
            bidder.run(prompt)
            log("BID", "bidder.run() returned — bid placed (inventory not yet assigned by server)")
            break
        except json.JSONDecodeError as e:
            log("BID", f"bidder.run() JSON error (attempt {attempt+1}/3): {e}")
            if attempt == 2:
                log("ERROR", "bidder.run() failed after 3 attempts, skipping bid")
        except Exception as e:
            log("ERROR", f"bidder.run() failed: {e}")
            break
    log("BID", "checking inventory right after bid (should still be empty)...")
    print_inventory()
    log("BID", "inventory will be available after server closes the bid phase")

def get_valid_recipes(inventory: dict, recipes: list) -> list:
    """Filtra le ricette che possono essere preparate con l'inventario attuale."""
    valid = []
    for recipe in recipes:
        ingredients = recipe.get("ingredients", {})
        if all(inventory.get(ing, 0) >= qty for ing, qty in ingredients.items()):
            valid.append(recipe)
    return valid


async def waiting_phase_started() -> None:
    log("BID", "waiting phase started — checking inventory NOW (after bid resolution)")
    inventory = get_inventory()
    log("BID", f"inventory has {len(inventory)} ingredients: {dict(inventory)}")
    print_inventory()
    valid_recipes = get_valid_recipes(inventory, all_recipes)
    log("MENU", f"{len(valid_recipes)} ricette preparabili su {len(all_recipes)} totali")

    if valid_recipes:
        # ── Ordinamento basato sulla strategia ──
        if current_strategy == "prestigio":
            valid_recipes.sort(key=lambda r: r["prestige"], reverse=True)
            log("STRATEGY", "sorted recipes by prestige DESC")
        elif current_strategy == "velocità":
            valid_recipes.sort(key=lambda r: r["preparationTimeMs"])
            log("STRATEGY", "sorted recipes by preparationTimeMs ASC")
        else:
            random.shuffle(valid_recipes)
            log("STRATEGY", f"strategy={current_strategy}, using random shuffle")

        for r in valid_recipes[:15]:
            log("MENU", f"  - {r['name']} (prestige={r['prestige']}, time={r['preparationTimeMs']}ms)")

        selected = valid_recipes[:min(12, len(valid_recipes))]
        current_menu.clear()
        current_menu.extend(r["name"] for r in selected)
        log("MENU", f"selezionate top {len(selected)} ricette (strategy={current_strategy})")

        # ── Prompt menu dinamico in base alla strategia ──
        recipe_names = str([r["name"] for r in selected])
        if current_strategy == "prezzo123":
            menu_prompt = (
                "Aggiorna il menu con esattamente queste ricette: " + recipe_names
                + ". IMPORTANTE: Siamo in modalita' economica. Metti prezzi bassi, "
                "tra 100 e 200 per piatto, per attirare piu' clienti."
            )
        elif current_strategy == "prestigio123":
            menu_prompt = (
                "Aggiorna il menu con esattamente queste ricette: " + recipe_names
                + ". Questi sono piatti prestigiosi. Metti prezzi alti, "
                "tra 500 e 800 per piatto."
            )
        else:
            menu_prompt = "Aggiorna il menu con esattamente queste ricette: " + recipe_names

        menu.run(menu_prompt)
    else:
        log("MENU", "Nessuna ricetta preparabile con l'inventario attuale!")
    log("EVENT", "waiting phase started")


async def serving_phase_started() -> None:
    log("EVENT", "serving phase started")
    if current_menu:
        log("MENU", f"menu attivo ({len(current_menu)} piatti):")
        for name in current_menu:
            log("MENU", f"  - {name}")
    else:
        log("MENU", "nessun menu attivo")


async def end_turn() -> None:
    log("EVENT", "turn ended")

def get_meals(turn_id: int) -> list:
    import requests
    response = requests.get(
        f"{BASE_URL}/meals",
        params={"turn_id": turn_id, "restaurant_id": 15},
        headers={"x-api-key": TEAM_API_KEY},
    )
    response.raise_for_status()
    return response.json()


async def client_spawned(data: dict[str, Any]) -> None:
    log("SPAWN", f"--- client_spawned raw data: {data}")
    client_name = data.get("clientName", "unknown")
    order_text = str(data.get("orderText", "unknown"))
    order_text_raw = order_text
    order_text = order_text.lower().replace("i'd like a ", "").replace("i'd like ", "")

    log("SPAWN", f"client={client_name!r}  order_raw={order_text_raw!r}  order_clean={order_text!r}")

    # 1. Fetch meals to get client_id and intolerances
    log("SPAWN", f"calling get_meals(turn_id={current_turn_id}) ...")
    try:
        meals = get_meals(current_turn_id)
        log("SPAWN", f"get_meals returned {len(meals)} entries: {meals}")
    except Exception as e:
        log("ERROR", f"get_meals failed: {e}")
        return

    # 2. Find this client in the meals list
    log("SPAWN", f"searching for clientName={client_name!r} in meals ...")
    client_meal = None
    for i, meal in enumerate(meals):
        customer = meal.get("customer") or {}
        meal_name = customer.get("name", "")
        executed = meal.get("executed", False)
        log("SPAWN", f"  meal[{i}]: name={meal_name!r} executed={executed}")
        if meal_name == client_name and not executed:
            client_meal = meal
            log("SPAWN", f"  -> matched at index {i}")
            break

    if not client_meal:
        log("ERROR", f"client '{client_name}' not found in meals (checked {len(meals)} entries)")
        return

    client_id = client_meal.get("customerId") or client_meal.get("id")

    # Parse intolerances from the order text (e.g. "I'm intolerant to X")
    intolerances: set[str] = set()
    intol_marker = "intolerant to "
    intol_idx = order_text.find(intol_marker)
    if intol_idx != -1:
        intol_str = order_text[intol_idx + len(intol_marker):]
        # Clean up trailing punctuation / extra text
        for sep in [".", ",", ";"]:
            intol_str = intol_str.split(sep)[0]
        intolerances = {i.strip() for i in intol_str.split(",") if i.strip()}

    log("SPAWN", f"client_id={client_id!r}  intolerances={intolerances}")

    # 3. Match order to a recipe: best ingredient-overlap, respecting intolerances
    #    Only consider recipes that are on the current menu
    menu_set = set(current_menu)
    menu_recipes = [r for r in all_recipes if r["name"] in menu_set]

    # Build set of ingredient names mentioned in the order (case-insensitive)
    order_lower = order_text.lower()
    log("SPAWN", f"matching order against {len(menu_recipes)} menu recipes (of {len(all_recipes)} total) ...")
    best_match = None
    best_score = -1

    skipped_intol = 0
    for recipe in menu_recipes:
        recipe_ingredients = set(recipe["ingredients"].keys())
        blocked = intolerances & recipe_ingredients
        if blocked:
            skipped_intol += 1
            continue

        # Count how many of this recipe's ingredients appear in the order text
        score = sum(1 for ing in recipe_ingredients if ing.lower() in order_lower)

        if score > best_score:
            best_score = score
            best_match = recipe
            matched = [ing for ing in recipe_ingredients if ing.lower() in order_lower]
            log("SPAWN", f"  new best: {recipe['name']!r}  score={score}/{len(recipe_ingredients)}  matched={matched}")

    log("SPAWN", f"skipped {skipped_intol} recipes due to intolerances, best_score={best_score}")

    # Fallback: pick highest-prestige compatible dish
    if not best_match or best_score == 0:
        log("SPAWN", "no word-match found, falling back to highest-prestige compatible dish from menu")
        compatible = [
            r for r in all_recipes
            if r["name"] in menu_set and not (intolerances & set(r["ingredients"].keys()))
        ]
        log("SPAWN", f"  {len(compatible)} compatible recipes available")
        if compatible:
            best_match = max(compatible, key=lambda r: r["prestige"])
            log("SPAWN", f"  fallback pick: {best_match['name']!r} prestige={best_match['prestige']}")

    if not best_match:
        log("ERROR", f"no compatible dish found for {client_name}")
        return

    # 4. Verify we have inventory for the chosen dish before preparing
    inventory = get_inventory()
    required = best_match.get("ingredients", {})
    missing = {ing: qty for ing, qty in required.items() if inventory.get(ing, 0) < qty}
    if missing:
        log("SPAWN", f"chosen dish {best_match['name']!r} missing ingredients: {missing}, skipping")
        return

    dish_name = best_match["name"]
    log("SPAWN", f"chosen dish: {dish_name!r}  prestige={best_match['prestige']}  cook_ms={best_match['preparationTimeMs']}  ingredients={list(best_match['ingredients'].keys())}")

    # 5. Track this dish -> client_id mapping
    pending_dishes.setdefault(dish_name, []).append(client_id)
    log("SPAWN", f"pending_dishes now: { {k: v for k, v in pending_dishes.items()} }")

    log("ACTION", f">>> prepare_dish '{dish_name}' for client {client_name!r} (id={client_id})")
    prepara.run(f"Prepara il piatto '{dish_name}'")
    log("SPAWN", f"prepare_dish call returned for '{dish_name}'")



async def preparation_complete(data: dict[str, Any]) -> None:
    log("READY", f"--- preparation_complete raw data: {data}")
    dish_name = data.get("dish", "unknown")

    log("READY", f"dish ready: {dish_name!r}")
    log("READY", f"pending_dishes state: { {k: v for k, v in pending_dishes.items()} }")

    # Pop the first client waiting for this dish
    clients = pending_dishes.get(dish_name, [])
    log("READY", f"clients waiting for '{dish_name}': {clients}")
    if not clients:
        log("ERROR", f"no pending client for dish '{dish_name}' — cannot serve!")
        return

    client_id = clients.pop(0)
    if not clients:
        del pending_dishes[dish_name]
    log("READY", f"popped client_id={client_id!r}, remaining for this dish: {clients}")
    log("READY", f"pending_dishes after pop: { {k: v for k, v in pending_dishes.items()} }")

    log("ACTION", f">>> serve_dish '{dish_name}' to client {client_id!r}")
    servi.run(f"Servi il piatto '{dish_name}' al cliente con id '{client_id}'")
    log("READY", f"serve_dish call returned for '{dish_name}' -> client {client_id!r}")

    inventory = get_inventory()
    log("INVENTORY", f"Dopo serve: {len(inventory)} ingredienti in inventario")


async def message(data: dict[str, Any]) -> None:
    sender = data.get("sender", "unknown")
    text = data.get("payload", "")
    log("EVENT", f"message from {sender}: {text}")
    if "Bid phase closed" in str(text):
        log("BID", ">>> server confirmed bid phase closed! Checking inventory...")
        inventory = get_inventory()
        log("BID", f"post-bid inventory: {len(inventory)} ingredients: {dict(inventory)}")
        print_inventory()


async def game_phase_changed(data: dict[str, Any]) -> None:
    phase = data.get("phase", "unknown")
    handlers: dict[str, Callable[[], Awaitable[None]]] = {
        "speaking": speaking_phase_started,
        "closed_bid": closed_bid_phase_started,
        "waiting": waiting_phase_started,
        "serving": serving_phase_started,
        "stopped": end_turn,
    }
    handler = handlers.get(phase)
    if handler:
        await handler()
    else:
        log("EVENT", f"unknown phase: {phase}")


async def game_reset(data: dict[str, Any]) -> None:
    if data:
        log("EVENT", f"game reset: {data}")
    else:
        log("EVENT", "game reset")


EVENT_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {
    "game_started": game_started,
    "game_phase_changed": game_phase_changed,
    "game_reset": game_reset,
    "client_spawned": client_spawned,
    "preparation_complete": preparation_complete,
    "message": message,
}

##########################################################################################
#                                    DANGER ZONE                                         #
##########################################################################################
# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.


# It is the central event dispatcher used by all handlers.
async def dispatch_event(event_type: str, event_data: dict[str, Any]) -> None:
    handler = EVENT_HANDLERS.get(event_type)
    if not handler:
        return
    try:
        await handler(event_data)
    except Exception as exc:
        log("ERROR", f"handler failed for {event_type}: {exc}")


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# It parses SSE lines and translates them into internal events.
async def handle_line(raw_line: bytes) -> None:
    if not raw_line:
        return

    # dump the raw line to file for debugging
    decoded = raw_line.decode("utf-8", errors="ignore").strip()
    if decoded and not decoded.startswith("Restaurant"):
        with open("debug_sse.log", "a") as f:
            f.write(decoded + "\n")

    line = decoded
    if not line:
        return

    # Standard SSE data format: data: ...
    if line.startswith("data:"):
        payload = line[5:].strip()
        if payload == "connected":
            log("SSE", "connected")
            return
        line = payload

    try:
        event_json = json.loads(line)
    except json.JSONDecodeError:
        log("SSE", f"raw: {line}")
        return

    event_type = event_json.get("type", "unknown")
    event_data = event_json.get("data", {})
    if isinstance(event_data, dict):
        await dispatch_event(event_type, event_data)
    else:
        await dispatch_event(event_type, {"value": event_data})


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# It owns the SSE HTTP connection lifecycle.
async def listen_once(session: aiohttp.ClientSession) -> None:
    url = f"{BASE_URL}/events/{TEAM_ID}"
    headers = {"Accept": "text/event-stream", "x-api-key": TEAM_API_KEY}

    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        log("SSE", "connection open")
        async for line in response.content:
            await handle_line(line)


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# It controls script exit behavior when the SSE connection drops.
async def listen_once_and_exit_on_drop() -> None:
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        await listen_once(session)
        log("SSE", "connection closed, exiting")


# DO NOT EDIT THE CODE BELOW until you are sure what you are doing.
# Keep this minimal to avoid changing startup behavior.
async def main() -> None:
    log("INIT", f"team={TEAM_ID} base_url={BASE_URL}")
    await listen_once_and_exit_on_drop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("INIT", "client stopped")