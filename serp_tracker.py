import requests
import json
import os
import re
from datetime import date, timedelta
from google.oauth2.service_account import Credentials
import gspread
import time

AHREFS_API_KEY = os.environ.get("AHREFS_API_KEY")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0BATELBR46")
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID")
GOOGLE_SHEETS_CREDENTIALS = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
HISTORY_FILE = "serp_history.json"

CONTACT_PAGES = ["", "/contact", "/about", "/contacts", "/kontakt", "/uber-uns"]

# Сайти які позначаємо в колонці Name
NAMED_SITES = {
    "youtube.com": "YouTube",
    "play.google.com": "Google Play",
    "acma.gov.au": "ACMA",
    "wikipedia.org": "Wikipedia",
    "facebook.com": "Facebook",
}

# Ключові слова в URL для визначення рев'юшників
REVIEW_KEYWORDS = ["/review", "/reviews", "/best", "/top", "/ranking", "/ratings"]

KEYWORDS = {
    "AU": ["online casino","online casino australia","online casino australia real money","australian online casino","best online casino australia","casino online","best australian online casino","online pokies","online pokies australia","pokies online","online pokies real money","payid pokies","best online pokies australia","australian online pokies","no deposit bonus casino","free spins no deposit","no deposit free spins","online casino no deposit bonus"],
    "CA": ["online casino","online casino canada","casino en ligne","1$ deposit casino","casino bonus","best casino online","best online casino canada","no deposit bonus casino","no deposit bonus casino canada","casino no deposit bonus","no deposit casino","casino bonus sans dépôt","casino rewards bonus sans dépôt","best online casino","$5 minimum deposit casino canada"],
    "NZ": ["$1 deposit casino","$1 deposit casino nz","1 dollar deposit casino","online casino nz","online casino","best online casino nz","nz online casino","best online casino","casino online","no deposit bonus casino","deposit $1 get $20 nz","1 deposit casino"],
    "DE": ["online casino","online casino deutschland","casino online","bestes online casino","beste online casino","casino bonus ohne einzahlung","10 euro bonus ohne einzahlung casino","online casino kostenlos","online casino bonus ohne einzahlung","crypto casino","bitcoin casino","online casino ohne limit"],
    "AT": ["online casino","online casino österreich","casino online","casino austria","casino online österreich","casino bonus ohne einzahlung","online casino bonus ohne einzahlung","bitcoin casino","crypto casino"]
}

GEO_FLAGS = {"AU": "🇦🇺", "CA": "🇨🇦", "NZ": "🇳🇿", "DE": "🇩🇪", "AT": "🇦🇹"}

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
        ws = spreadsheet.add_worksheet(title=today_str, rows=5000, cols=11)
        ws.append_row(["Дата", "ГЕО", "Ключ", "Позиція", "URL", "DR", "Traffic", "Статус", "Contact", "Stag", "Name", "Manager", "Знайомий бренд", "Manager 7bit", "Comment"])
    return ws

def load_pages_data(gc):
    """Завантажує дані з вкладки Pages"""
    try:
        spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
        ws = spreadsheet.worksheet("Pages")
        rows = ws.get_all_values()
        if not rows:
            return {}

        headers = [h.strip().lower() for h in rows[0]]
        try:
            url_col = headers.index("top pages")
            stag_col = headers.index("stag")
            name_col = headers.index("name")
            manager_col = headers.index("manager")
            type_col = headers.index("type")
        except ValueError as e:
            print(f"  ⚠️ Колонка не знайдена в Pages: {e}")
            return {}

        pages_map = {}
        for row in rows[1:]:
            if len(row) <= max(url_col, stag_col, name_col, manager_col, type_col):
                continue
            page_url = row[url_col].strip()
            stag = row[stag_col].strip()
            name = row[name_col].strip()
            manager = row[manager_col].strip()
            page_type = row[type_col].strip().lower()
            if page_url:
                domain = extract_domain(page_url)
                if domain:
                    pages_map[domain] = {"stag": stag, "name": name, "manager": manager, "type": page_type}

        print(f"✅ Завантажено {len(pages_map)} доменів з вкладки Pages")
        return pages_map
    except Exception as e:
        print(f"  ⚠️ Помилка завантаження Pages: {e}")
        return {}

def load_manager_history(gc, today_str):
    """Завантажує історію менеджерів з попередніх вкладок"""
    try:
        spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
        all_sheets = spreadsheet.worksheets()
        manager_map = {}  # {domain: {stag, name, manager}}

        # Сортуємо вкладки за датою (від найстарішої до найновішої)
        date_sheets = []
        for ws in all_sheets:
            title = ws.title
            if title == today_str or title == "Pages":
                continue
            try:
                date.fromisoformat(title)
                date_sheets.append((title, ws))
            except ValueError:
                continue

        date_sheets.sort(key=lambda x: x[0])

        for title, ws in date_sheets:
            try:
                rows = ws.get_all_values()
                if not rows or len(rows) < 2:
                    continue

                headers = [h.strip().lower() for h in rows[0]]
                try:
                    url_col = headers.index("url")
                    manager_col = headers.index("manager")
                    stag_col = headers.index("stag")
                    name_col = headers.index("name")
                    status_col = headers.index("статус")
                except ValueError:
                    continue

                for row in rows[1:]:
                    if len(row) <= max(url_col, manager_col, stag_col, name_col, status_col):
                        continue
                    status = row[status_col].strip()
                    manager = row[manager_col].strip()
                    if status == "NEW" and manager:
                        url_val = row[url_col].strip()
                        domain = extract_domain(url_val)
                        if domain:
                            manager_map[domain] = {
                                "stag": row[stag_col].strip(),
                                "name": row[name_col].strip(),
                                "manager": manager
                            }
            except Exception:
                continue

        print(f"✅ Завантажено {len(manager_map)} доменів з історії вкладок")
        return manager_map
    except Exception as e:
        print(f"  ⚠️ Помилка завантаження історії: {e}")
        return {}

def load_friends_data(gc):
    """Завантажує список брендів друзів з вкладки Friends"""
    try:
        spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
        ws = spreadsheet.worksheet("Friends")
        rows = ws.get_all_values()
        if not rows or len(rows) < 2:
            return []

        headers = [h.strip().lower() for h in rows[0]]
        try:
            manager_col = headers.index("manager 7bit")
            brand_col = headers.index("знайомий бренд")
        except ValueError as e:
            print(f"  ⚠️ Колонка не знайдена в Friends: {e}")
            return []

        friends = []
        for row in rows[1:]:
            if len(row) <= max(manager_col, brand_col):
                continue
            brand = row[brand_col].strip()
            manager = row[manager_col].strip()
            if brand:
                friends.append({"brand": brand, "manager": manager})

        print(f"✅ Завантажено {len(friends)} брендів друзів")
        return friends
    except Exception as e:
        print(f"  ⚠️ Помилка завантаження Friends: {e}")
        return []

def find_friend_brands(page_url, base_url, friends):
    """Шукає бренди друзів на сторінці з топу та на головній"""
    if not friends:
        return []

    found_brands = {}
    headers_req = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    urls_to_check = set()
    if page_url:
        urls_to_check.add(page_url)
    if base_url:
        urls_to_check.add(base_url)

    for url_to_check in urls_to_check:
        try:
            r = requests.get(url_to_check, headers=headers_req, timeout=10, allow_redirects=True)
            if r.status_code != 200:
                continue
            html = r.text.lower()

            for friend in friends:
                brand = friend["brand"]
                if brand.lower() in html:
                    if brand not in found_brands:
                        found_brands[brand] = friend["manager"]
        except Exception:
            continue

    return [{"brand": b, "manager": m} for b, m in found_brands.items()]

def get_site_name(domain):
    """Повертає назву для відомих сайтів"""
    for known_domain, name in NAMED_SITES.items():
        if known_domain in domain:
            return name
    return ""

def is_review_site(url):
    """Перевіряє чи є сайт рев'юшником по URL"""
    url_lower = url.lower()
    return any(kw in url_lower for kw in REVIEW_KEYWORDS)

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
        "select": "url,position,domain_rating,page_type,traffic"
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

def apply_green_formatting(ws, row_indices, spreadsheet):
    """Підсвічує рядки рев'юшників зеленим"""
    if not row_indices:
        return
    green = {"backgroundColor": {"red": 0.56, "green": 0.93, "blue": 0.56}}
    requests_batch = []
    for row_idx in row_indices:
        requests_batch.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 15
                },
                "cell": {"userEnteredFormat": green},
                "fields": "userEnteredFormat.backgroundColor"
            }
        })
    if requests_batch:
        spreadsheet.batch_update({"requests": requests_batch})

def main():
    today_str = str(date.today())
    print(f"Запуск SERP Tracker — {today_str}")

    gc = get_sheets_client()
    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
    ws = get_or_create_sheet(gc, today_str)

    # Завантажуємо дані
    pages_map = load_pages_data(gc)
    manager_history = load_manager_history(gc, today_str)
    friends_list = load_friends_data(gc)

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
            time.sleep(2)

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
                    if not url_val or url_val in prev_urls:
                        continue
                    domain = extract_domain(url_val)
                    # Пропускаємо casino brands
                    page_info = pages_map.get(domain, {})
                    if page_info.get("type", "") == "casino brand":
                        continue
                    new_sites.append({
                        "geo": geo,
                        "keyword": keyword,
                        "position": pos.get("position", ""),
                        "url": url_val,
                        "domain": domain,
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

                # Визначаємо info: пріоритет Pages → історія вкладок
                if domain in pages_map:
                    page_info = pages_map[domain]
                elif domain in manager_history:
                    page_info = manager_history[domain]
                else:
                    page_info = {}

                # Визначаємо Name
                site_name = get_site_name(domain)
                if not site_name:
                    site_name = page_info.get("name", "")

                sheets_rows.append([
                    today_str,
                    geo,
                    keyword,
                    organic_counter,
                    url_val,
                    pos.get("domain_rating", ""),
                    pos.get("traffic", ""),
                    "",  # Статус
                    "",  # Contact
                    page_info.get("stag", ""),
                    site_name,
                    page_info.get("manager", ""),
                    "",  # Знайомий бренд
                    "",  # Manager 7bit
                    ""   # Comment
                ])

    # Збираємо контакти та бренди друзів для нових сайтів
    contacts_map = {}
    friends_map = {}  # {url: [{brand, manager}]}
    new_urls = {s['url'] for s in new_sites}

    if new_sites:
        seen_new_domains = set()
        for s in new_sites:
            domain = s['domain']
            url_val = s['url']
            base = get_base_url(url_val)
            if domain not in seen_new_domains:
                seen_new_domains.add(domain)
                print(f"  Сканую контакти: {url_val}")
                contacts_map[domain] = find_contacts(url_val)
                print(f"  Сканую бренди друзів: {url_val}")
                friends_map[url_val] = find_friend_brands(url_val, base, friends_list)

    # Оновлюємо статус і контакти в рядках Sheets
    for row in sheets_rows:
        url = row[4]
        domain = extract_domain(url)
        if url in new_urls:
            row[7] = "NEW"
            # Бренди друзів
            found = friends_map.get(url, [])
            if found:
                row[12] = ", ".join(f["brand"] for f in found)
                row[13] = ", ".join(f["manager"] for f in found)
        contacts = contacts_map.get(domain, {})
        all_contacts = []
        all_contacts.extend(contacts.get("emails", []))
        all_contacts.extend(contacts.get("whatsapps", []))
        all_contacts.extend(contacts.get("telegrams", []))
        row[8] = ", ".join(all_contacts)

    # Записуємо в Google Sheets
    if sheets_rows:
        # Знаходимо поточну кількість рядків для визначення індексів
        existing_rows = len(ws.get_all_values())
        ws.append_rows(sheets_rows, value_input_option="RAW")
        print(f"✅ Записано {len(sheets_rows)} рядків в Google Sheets")

        # Підсвічуємо рев'юшників зеленим
        review_row_indices = []
        for i, row in enumerate(sheets_rows):
            url = row[4]
            if is_review_site(url):
                review_row_indices.append(existing_rows + i)

        if review_row_indices:
            apply_green_formatting(ws, review_row_indices, spreadsheet)
            print(f"✅ Підсвічено {len(review_row_indices)} рев'юшників зеленим")

    # Відправка в Slack — тільки нові сайти
    if new_sites:
        new_block = f"📊 *SERP Report — {today_str}*\n{'─' * 40}\n🚨 *НОВІ САЙТИ СЬОГОДНІ:*\n"
        send_slack(new_block)

        for s in new_sites:
            domain = s['domain']
            flag = GEO_FLAGS.get(s['geo'], s['geo'])
            contacts = contacts_map.get(domain, {})

            all_contacts = []
            all_contacts.extend(contacts.get("emails", []))
            all_contacts.extend(contacts.get("whatsapps", []))
            all_contacts.extend(contacts.get("telegrams", []))
            contacts_str = ", ".join(all_contacts) if all_contacts else ""

            # Визначаємо info: пріоритет Pages → історія
            if domain in pages_map:
                page_info = pages_map[domain]
            elif domain in manager_history:
                page_info = manager_history[domain]
            else:
                page_info = {}

            site_name = get_site_name(domain)
            if not site_name:
                site_name = page_info.get("name", "")

            stag = page_info.get("stag", "")
            manager = page_info.get("manager", "")

            found_friends = friends_map.get(s['url'], [])

            site_block = f"🆕 {s['url']}\n"
            site_block += f"   {flag} {s['geo']} | {s['keyword']} | позиція #{s['position']} | DR:{s['dr']}\n"
            if site_name:
                site_block += f"   📝 {site_name}\n"
            if stag:
                site_block += f"   🏷 Stag: {stag}\n"
            if manager:
                site_block += f"   👤 Manager: {manager}\n"
            if found_friends:
                seen_managers = set()
                for fb in found_friends:
                    manager_7bit = fb['manager']
                    brand_line = f"   🤝 Бренд: {fb['brand']}"
                    if manager_7bit not in seen_managers:
                        brand_line += f" | Manager 7bit: {manager_7bit}"
                        seen_managers.add(manager_7bit)
                    site_block += brand_line + "\n"
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
