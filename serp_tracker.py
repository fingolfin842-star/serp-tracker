import requests
import json
import os
from datetime import date, timedelta

import os
AHREFS_API_KEY = os.environ.get("AHREFS_API_KEY", "bwdex6ubgVa4tcx0-CQnItXujV0sZRLk1c_Q-tak")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/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")
HISTORY_FILE = "serp_history.json"

KEYWORDS = {
    "AU": ["online casino","online casino australia","online casino australia real money","australian online casino","best online casino australia","casino online","best australian online casino","online pokies","online pokies australia","pokies online","online pokies real money","payid pokies","best online pokies australia","australian online pokies","no deposit bonus casino","free spins no deposit","no deposit free spins","online casino no deposit bonus"],
    "CA": ["online casino","online casino canada","casino en ligne","1$ deposit casino","casino bonus","best casino online","best online casino canada","no deposit bonus casino","no deposit bonus casino canada","casino no deposit bonus","no deposit casino","casino bonus sans dépôt","casino rewards bonus sans dépôt","best online casino","$5 minimum deposit casino canada"],
    "NZ": ["$1 deposit casino","$1 deposit casino nz","1 dollar deposit casino","online casino nz","online casino","best online casino nz","nz online casino","best online casino","casino online","no deposit bonus casino","deposit $1 get $20 nz","1 deposit casino"],
    "DE": ["online casino","online casino deutschland","casino online","bestes online casino","beste online casino","casino bonus ohne einzahlung","10 euro bonus ohne einzahlung casino","online casino kostenlos","online casino bonus ohne einzahlung","crypto casino","bitcoin casino","online casino ohne limit"],
    "AT": ["online casino","online casino österreich","casino online","casino austria","casino online österreich","casino bonus ohne einzahlung","online casino bonus ohne einzahlung","bitcoin casino","crypto casino"]
}

GEO_FLAGS = {"AU": "🇦🇺", "CA": "🇨🇦", "NZ": "🇳🇿", "DE": "🇩🇪", "AT": "🇦🇹"}
GEO_NAMES = {"AU": "Australia", "CA": "Canada", "NZ": "New Zealand", "DE": "Germany", "AT": "Austria"}

def extract_domain(url):
    if not url or not isinstance(url, str):
        return ""
    if url.startswith("http"):
        parts = url.split("/")
        return parts[2] if len(parts) > 2 else ""
    return url

def get_serp(keyword, country):
    url = "https://api.ahrefs.com/v3/serp-overview/serp-overview"
    headers = {"Authorization": f"Bearer {AHREFS_API_KEY}", "Accept": "application/json"}
    params = {
        "keyword": keyword,
        "country": country.lower(),
        "top_positions": 30,
        "select": "url,position,domain_rating,page_type"
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            all_positions = r.json().get("positions", [])

            # Рахуємо скільки разів зустрічається кожна позиція
            position_count = {}
            for pos in all_positions:
                p = pos.get("position")
                if p is not None:
                    position_count[p] = position_count.get(p, 0) + 1

            result = []
            seen_positions = set()

            for pos in all_positions:
                url_val = pos.get("url")
                if not url_val or not isinstance(url_val, str) or not url_val.startswith("http"):
                    continue

                p = pos.get("position")
                is_paa = position_count.get(p, 0) > 1

                # Для звичайних результатів — пропускаємо дублі позицій
                if not is_paa and p in seen_positions:
                    continue

                pos["is_paa"] = is_paa
                result.append(pos)

                if not is_paa:
                    seen_positions.add(p)

            # Сортуємо по позиції
            result.sort(key=lambda x: (x.get("position") or 99, x.get("is_paa", False)))

            # Беремо топ 10 органічних + всі PAA які між ними
            organic_count = 0
            final = []
            for pos in result:
                if not pos.get("is_paa"):
                    organic_count += 1
                final.append(pos)
                if organic_count >= 10:
                    break

            return final
        else:
            print(f"  Помилка {r.status_code} для '{keyword}' / {country}")
            return []
    except Exception as e:
        print(f"  Виняток: {e}")
        return []

def send_slack(text):
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=30)
        if r.status_code != 200:
            print(f"  ⚠️ Slack помилка {r.status_code}: {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        print(f"  ⚠️ Slack виняток: {e}")
        return False

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(data):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    today_str = str(date.today())
    print(f"Запуск SERP Tracker — {today_str}")

    history = load_history()
    yesterday_str = str(date.today() - timedelta(days=1))
    yesterday_data = history.get(yesterday_str, {})
    is_first_run = len(yesterday_data) == 0

    today_data = {}
    all_results = {}
    new_sites = []

    for geo, keywords in KEYWORDS.items():
        all_results[geo] = {}
        for keyword in keywords:
            print(f"  {geo} | {keyword}")
            positions = get_serp(keyword, geo)
            all_results[geo][keyword] = positions

            urls_today = set()
            for pos in positions:
                if not pos.get("is_paa"):
                    url_val = pos.get("url", "")
                    if url_val:
                        urls_today.add(url_val)

            today_data[f"{geo}|{keyword}"] = list(urls_today)

            if not is_first_run:
                prev_urls = set(yesterday_data.get(f"{geo}|{keyword}", []))
                for pos in positions:
                    if pos.get("is_paa"):
                        continue
                    url_val = pos.get("url", "")
                    if url_val and url_val not in prev_urls:
                        new_sites.append({
                            "geo": geo,
                            "keyword": keyword,
                            "position": pos.get("position", ""),
                            "url": url_val,
                            "domain": extract_domain(url_val),
                            "dr": pos.get("domain_rating", "")
                        })

    send_slack(f"📊 *SERP Report — {today_str}*\n{'─' * 40}")

    for geo, keywords_data in all_results.items():
        flag = GEO_FLAGS.get(geo, "")
        geo_name = GEO_NAMES.get(geo, geo)
        geo_block = f"\n*{flag} {geo_name}*\n{'─' * 40}\n"

        for keyword, positions in keywords_data.items():
            geo_block += f"\n*{keyword} [{geo}]*\n"
            if not positions:
                geo_block += "  _немає даних_\n"
                continue

            organic_counter = 0
            current_paa_position = None

            for pos in positions:
                url_val = pos.get("url", "")
                dr = pos.get("domain_rating", "")
                p = pos.get("position", "")
                is_paa = pos.get("is_paa", False)

                if is_paa:
                    geo_block += f"  ✖  {url_val}  DR:{dr}  _(People also ask)_\n"
                else:
                    organic_counter += 1
                    geo_block += f"  #{organic_counter}  {url_val}  DR:{dr}\n"

        send_slack(geo_block)

    if new_sites:
        new_block = f"\n{'─' * 40}\n🚨 *НОВІ САЙТИ СЬОГОДНІ:*\n"
        for s in new_sites:
            flag = GEO_FLAGS.get(s['geo'], s['geo'])
            new_block += f"🆕 *{s['url']}* — {flag} {s['geo']} | {s['keyword']} | позиція #{s['position']} | DR:{s['dr']}\n"
        send_slack(new_block)
    elif not is_first_run:
        send_slack("✅ *Нових сайтів сьогодні немає*")

    if is_first_run:
        send_slack("_ℹ️ Перший запуск — звірка з попереднім днем почнеться завтра_")

    history[today_str] = today_data
    keys_to_keep = sorted(history.keys())[-7:]
    history = {k: history[k] for k in keys_to_keep}
    save_history(history)

    print("Готово!")

if __name__ == "__main__":
    main()
