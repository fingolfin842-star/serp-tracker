import requests
import json
import os
import re
from datetime import date, timedelta
from google.oauth2.service_account import Credentials
import gspread

AHREFS_API_KEY = os.environ.get("AHREFS_API_KEY")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0BATELBR46")
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID")
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
HISTORY_FILE = "serp_history.json"

CONTACT_PAGES = ["", "/contact", "/about", "/contacts", "/kontakt", "/uber-uns"]

KEYWORDS = {
    "AU": ["online casino","online casino australia","online casino australia real money","australian online casino","best online casino australia","casino online","best australian online casino","online pokies","online pokies australia","pokies online","online pokies real money","payid pokies","best online pokies australia","australian online pokies","no deposit bonus casino","free spins no deposit","no deposit free spins","online casino no deposit bonus"],
    "CA": ["online casino","online casino canada","casino en ligne","1$ deposit casino","casino bonus","best casino online","best online casino canada","no deposit bonus casino","no deposit bonus casino canada","casino no deposit bonus","no deposit casino","casino bonus sans dépôt","casino rewards bonus sans dépôt","best online casino","$5 minimum deposit casino canada"],
    "NZ": ["$1 deposit casino","$1 deposit casino nz","1 dollar deposit casino","online casino nz","online casino","best online casino nz","nz online casino","best online casino","casino online","no deposit bonus casino","deposit $1 get $20 nz","1 deposit casino"],
    "DE": ["online casino","online casino deutschland","casino online","bestes online casino","beste online casino","casino bonus ohne einzahlung","10 euro bonus ohne einzahlung casino","online casino kostenlos","online casino bonus ohne einzahlung","crypto casino","bitcoin casino","online casino ohne limit"],
    "AT": ["online casino","online casino österreich","casino online","casino austria","casino online österreich","casino bonus ohne einzahlung","online casino bonus ohne einzahlung","bitcoin casino","crypto casino"]
}

GEO_FLAGS = {"AU": "🇦🇺", "CA": "🇨🇦", "NZ": "🇳🇿", "DE": "🇩🇪", "AT": "🇦🇹"}
GEO_NAMES = {"AU": "Australia", "CA": "Canada", "NZ": "New Zealand", "DE": "Germany", "AT": "Austria"}

def get_sheets_client():
    creds_json = json.loads(GOOGLE_SHEETS_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return gspread.authorize(creds)

def get_or_create_sheet(gc, today_str):
    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
    try:
        ws = spreadsheet.worksheet(today_str)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=today_str, rows=5000, cols=10)
        ws.append_row(["Дата", "ГЕО", "Ключ", "Позиція", "URL", "DR", "Статус", "Contact", "Stag", "Manager"])
    return ws

def load_pages_data(gc):
    """Завантажує дані з вкладки Pages і повертає словник {domain: {stag, manager}}"""
    try:
        spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
        ws = spreadsheet.worksheet("Pages")
        rows = ws.get_all_values()
        if not rows:
            return {}

        # Знаходимо індекси колонок
        headers = [h.strip().lower() for h in rows[0]]
        try:
            url_col = headers.index("top pages")
            stag_col = headers.index("stag")
            manager_col = headers.index("manager")
        except ValueError as e:
            print(f"  ⚠️ Колонка не знайдена в Pages: {e}")
            return {}

        pages_map = {}
        for row in rows[1:]:
            if len(row) <= max(url_col, stag_col, manager_col):
                continue
            page_url = row[url_col].strip()
            stag = row[stag_col].strip()
            manager = row[manager_col].strip()
            if page_url:
                domain = extract_domain(page_url)
                if domain:
                    pages_map[domain] = {"stag": stag, "manager": manager}

        print(f"✅ Завантажено {len(pages_map)} доменів з вкладки Pages")
        return pages_map

    except Exception as e:
        print(f"  ⚠️ Помилка завантаження Pages: {e}")
        return {}

def extract_domain(url):
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    if url.startswith("http"):
        parts = url.split("/")
        domain = parts[2] if len(parts) > 2 else ""
        return domain.replace("www.", "")
    return url.replace("www.", "")

def get_base_url(url):
    if not url or not isinstance(url, str):
        return ""
    if url.startswith("http"):
        parts = url.split("/")
        return f"{parts[0]}//{parts[2]}"
    return ""

def find_contacts(site_url):
    base_url = get_base_url(site_url)
    if not base_url:
        return {}

    emails = set()
    whatsapps = set()
    telegrams = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for page in CONTACT_PAGES:
        url_to_check = f"{base_url}{page}"
        try:
            r = requests.get(url_to_check, headers=headers, timeout=10, allow_redirects=True)
            if r.status_code != 200:
                continue
            html = r.text

            found_emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', html)
            for e in found_emails:
                if not any(skip in e.lower() for skip in ["example", "sentry", "wixpress", "schema", "pixel", "jquery", "png", "jpg", "svg", "webpack"]):
                    emails.add(e.lower())

            found_wa = re.findall(r'(?:wa\.me|whatsapp\.com/send)[/\?][\+\d%A-Za-z=&]+', html)
            for wa in found_wa:
                whatsapps.add(f"https://{wa}" if not wa.startswith("http") else wa)

            found_tg = re.findall(r't\.me/[A-Za-z0-9_\+]+', html)
            for tg in found_tg:
                telegrams.add(f"https://{tg}")

            if emails or whatsapps or telegrams:
                break

        except Exception:
            continue

    return {
        "emails": list(emails)[:3],
        "whatsapps": list(whatsapps)[:3],
        "telegrams": list(telegrams)[:3]
    }

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
                if not is_paa and p in seen_positions:
                    continue
                pos["is_paa"] = is_paa
                result.append(pos)
                if not is_paa:
                    seen_positions.add(p)

            result.sort(key=lambda x: (x.get("position") or 99, x.get("is_paa", False)))
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
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json; charset=utf-8"},
            json={"channel": SLACK_CHANNEL_ID, "text": text},
            timeout=30
        )
        data = r.json()
        if not data.get("ok"):
            print(f"  ⚠️ Slack помилка: {data.get('error')}")
        return data.get("ok", False)
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

    # Підключення до Google Sheets
    gc = get_sheets_client()
    ws = get_or_create_sheet(gc, today_str)

    # Завантажуємо дані з вкладки Pages
    pages_map = load_pages_data(gc)

    history = load_history()
    yesterday_str = str(date.today() - timedelta(days=1))
    yesterday_data = history.get(yesterday_str, {})
    is_first_run = len(yesterday_data) == 0

    today_data = {}
    all_results = {}
    new_sites = []
    sheets_rows = []

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

            # Рядки для Google Sheets
            organic_counter = 0
            for pos in positions:
                if pos.get("is_paa"):
                    continue
                organic_counter += 1
                url_val = pos.get("url", "")
                domain = extract_domain(url_val)
                page_info = pages_map.get(domain, {})
                sheets_rows.append([
                    today_str,
                    geo,
                    keyword,
                    organic_counter,
                    url_val,
                    pos.get("domain_rating", ""),
                    "",  # Статус
                    "",  # Contact
                    page_info.get("stag", ""),
                    page_info.get("manager", "")
                ])

    # Збираємо контакти для нових сайтів
    contacts_map = {}
    new_urls = {s['url'] for s in new_sites}

    if new_sites:
        seen_new_domains = set()
        for s in new_sites:
            domain = s['domain']
            if domain not in seen_new_domains:
                seen_new_domains.add(domain)
                print(f"  Сканую контакти: {s['url']}")
                contacts_map[domain] = find_contacts(s['url'])

    # Оновлюємо статус і контакти в рядках Sheets
    for row in sheets_rows:
        url = row[4]
        domain = extract_domain(url)
        if url in new_urls:
            row[6] = "NEW"
        contacts = contacts_map.get(domain, {})
        all_contacts = []
        all_contacts.extend(contacts.get("emails", []))
        all_contacts.extend(contacts.get("whatsapps", []))
        all_contacts.extend(contacts.get("telegrams", []))
        row[7] = ", ".join(all_contacts)

    # Записуємо в Google Sheets
    if sheets_rows:
        ws.append_rows(sheets_rows, value_input_option="RAW")
        print(f"✅ Записано {len(sheets_rows)} рядків в Google Sheets")

    # Відправка в Slack — тільки нові сайти
    if new_sites:
        new_block = f"📊 *SERP Report — {today_str}*\n{'─' * 40}\n🚨 *НОВІ САЙТИ СЬОГОДНІ:*\n"
        send_slack(new_block)

        seen_slack_domains = set()
        for s in new_sites:
            domain = s['domain']
            flag = GEO_FLAGS.get(s['geo'], s['geo'])
            contacts = contacts_map.get(domain, {})

            all_contacts = []
            all_contacts.extend(contacts.get("emails", []))
            all_contacts.extend(contacts.get("whatsapps", []))
            all_contacts.extend(contacts.get("telegrams", []))
            contacts_str = ", ".join(all_contacts) if all_contacts else ""

            page_info = pages_map.get(domain, {})
            stag = page_info.get("stag", "")
            manager = page_info.get("manager", "")

            site_block = f"🆕 {s['url']}\n"
            site_block += f"   {flag} {s['geo']} | {s['keyword']} | позиція #{s['position']} | DR:{s['dr']}\n"
            if stag:
                site_block += f"   🏷 Stag: {stag}\n"
            if manager:
                site_block += f"   👤 Manager: {manager}\n"
            if contacts_str:
                site_block += f"   📋 {contacts_str}\n"
            else:
                site_block += f"   _контакти не знайдені_\n"

            send_slack(site_block)

    elif not is_first_run:
        send_slack(f"📊 *SERP Report — {today_str}*\n✅ *Нових сайтів сьогодні немає*")

    if is_first_run:
        send_slack(f"📊 *SERP Report — {today_str}*\n_ℹ️ Перший запуск — звірка з попереднім днем почнеться завтра_")

    # Зберігаємо історію
    history[today_str] = today_data
    keys_to_keep = sorted(history.keys())[-7:]
    history = {k: history[k] for k in keys_to_keep}
    save_history(history)

    print("Готово!")

if __name__ == "__main__":
    main()
