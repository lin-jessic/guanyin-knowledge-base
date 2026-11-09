"""Temporary, view-only, token-gated LAN sharing for classroom phones.
Run from project root: py -3.12 share_lan.py
Do NOT use port forwarding or public tunnels. Close terminal to stop sharing.
"""
import os, secrets, socket, hashlib
from pathlib import Path
from flask import request, abort
from backend.app import app
from backend import store

PORT=int(os.environ.get('GUANYIN_SHARE_PORT','5050'))
TOKEN=secrets.token_urlsafe(24)
COOKIE='guanyin_lan_view'
FINGERPRINT=hashlib.sha256(TOKEN.encode()).hexdigest()

# Only GET/HEAD, no administrative endpoints or raw output, even if the cookie exists.
@app.before_request
def lan_readonly_guard():
    if request.method not in ('GET','HEAD'):
        abort(405)
    p=request.path
    if p.startswith(('/settings','/media/admin','/api/')):
        abort(404)
    supplied=request.args.get('access','')
    cookie=request.cookies.get(COOKIE,'')
    if not (secrets.compare_digest(supplied,TOKEN) or secrets.compare_digest(cookie,FINGERPRINT)):
        abort(403,'僅供持有本次分享 QR Code 的同網路裝置瀏覽')

@app.after_request
def lan_cookie(resp):
    if request.args.get('access') and secrets.compare_digest(request.args.get('access',''),TOKEN):
        resp.set_cookie(COOKIE,FINGERPRINT,httponly=True,samesite='Lax',secure=False,max_age=7200)
    resp.headers['X-Robots-Tag']='noindex, nofollow'
    return resp

def ip_for_lan():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        try:
            s.connect(('192.0.2.1',80))
            ip=s.getsockname()[0]
            if ip and not ip.startswith('127.'):return ip
        except OSError:pass
    return None

if __name__=='__main__':
    store.import_outputs()
    ip=ip_for_lan()
    if not ip:
        raise SystemExit('找不到電腦的區域網路 IPv4。請用 ipconfig 確認連線。')
    url=f'http://{ip}:{PORT}/?access={TOKEN}'
    folder=store.ROOT/'storage';folder.mkdir(exist_ok=True)
    try:
        import qrcode
        image=qrcode.make(url)
        path=folder/'lan_share_qr.png'
        image.save(path)
        print('QR Code 已存到：',path)
    except ImportError:
        print('缺少 qrcode 套件，請執行 py -3.12 -m pip install "qrcode[pil]"')
    print('\n僅限相同可互通的區域網路；不要上傳本次 QR 圖片。')
    print('手機開啟：',url)
    print('電腦管理中心仍只在另一個 127.0.0.1:5000 程序中運作。')
    print('停止分享：此視窗按 Ctrl+C。')
    app.run(host='0.0.0.0',port=PORT,debug=False,use_reloader=False)
