from pathlib import Path
p=Path('/home/ubuntu/work/talkin/Talkin1-main/bot.py')
s=p.read_text(encoding='utf-8')

# Add per-room moderation helpers after existing save function.
needle='''def _save_moderation_config(enabled, words):\n    clean = []\n    seen = set()\n    for word in words or []:\n        word = str(word).strip()\n        if not word:\n            continue\n        key = _norm_filter_text(word)\n        if key and key not in seen:\n            seen.add(key)\n            clean.append(word)\n    _save_local_json(MODERATION_FILE, {"enabled": bool(enabled), "words": clean})\n    return clean\n'''
insert=needle+'''\ndef _room_moderation_data():\n    data = _load_local_json(MODERATION_FILE, {})\n    return data if isinstance(data, dict) else {}\n\ndef _room_moderation_config(room):\n    data = _room_moderation_data()\n    rooms = data.get("rooms", {}) if isinstance(data.get("rooms"), dict) else {}\n    cfg = rooms.get(_norm_room(room), {})\n    if not isinstance(cfg, dict):\n        cfg = {}\n    return {\n        "enabled": bool(cfg.get("enabled", False)),\n        "repeat_limit": max(2, int(cfg.get("repeat_limit", 3) or 3)),\n        "words": [str(w).strip() for w in cfg.get("words", []) if str(w).strip()],\n    }\n\ndef _save_room_moderation(room, **changes):\n    data = _room_moderation_data()\n    rooms = data.get("rooms", {}) if isinstance(data.get("rooms"), dict) else {}\n    key = _norm_room(room)\n    cfg = _room_moderation_config(room)\n    cfg.update(changes)\n    cfg["repeat_limit"] = max(2, int(cfg.get("repeat_limit", 3) or 3))\n    rooms[key] = cfg\n    data["rooms"] = rooms\n    # Keep the legacy global filter fields intact for backward compatibility.\n    _save_local_json(MODERATION_FILE, data)\n    return cfg\n\ndef _room_manager(bot, room, sender):\n    if _is_master_name(sender):\n        return True\n    role = str(getattr(bot, "room_users", {}).get(room, {}).get(sender, "") or "").casefold()\n    return role in {"owner", "creator", "admin", "moderator", "moder"}\n'''
if needle not in s: raise SystemExit('moderation needle missing')
s=s.replace(needle,insert,1)

# master process must not inherit room and bootstrap must not restore rooms.
s=s.replace('''        env["MASTER_SERVICE_ENABLED"] = "1"\n        env["PRIMARY_BOT_ID"] = BOT_ID\n''','''        env["MASTER_SERVICE_ENABLED"] = "1"\n        env["GROUP_TO_JOIN"] = ""\n        env["FIRST_ROOM"] = ""\n        env["PRIMARY_BOT_ID"] = BOT_ID\n''',1)
s=s.replace('''        rooms_to_restore = {str(r).strip() for r in self.known_rooms if str(r).strip()}\n        if self.room:\n            rooms_to_restore.add(str(self.room).strip())\n''','''        rooms_to_restore = set() if MASTER_SERVICE_ENABLED else {str(r).strip() for r in self.known_rooms if str(r).strip()}\n        if self.room and not MASTER_SERVICE_ENABLED:\n            rooms_to_restore.add(str(self.room).strip())\n''',1)
s=s.replace('''        if not self.room:\n            missing.append("GROUP_TO_JOIN (or FIRST_ROOM)")\n''','''        if not self.room and not MASTER_SERVICE_ENABLED:\n            missing.append("GROUP_TO_JOIN (or FIRST_ROOM)")\n''',1)

# management authorization: allow room owner/master security commands.
old='''        if not _is_master_name(sender) and not (is_publish and _is_verified_user(sender)):\n            return False\n'''
new='''        security_command = bool(re.match(r"^(?:تشغيل|إيقاف) الحماية$", str(body or "").strip(), re.I) or re.match(r"^mr@\\d+$", str(body or "").strip(), re.I))\n        if not _is_master_name(sender) and not (is_publish and _is_verified_user(sender)) and not (security_command and room and _room_manager(self, room, sender)):\n            return False\n'''
if old not in s: raise SystemExit('management auth missing')
s=s.replace(old,new,1)

# insert room protection commands before backup.
needle='''        low=text.casefold()\n        if low in ("نسخ احتياطي", "نسخه احتياطيه", "backup", "full backup"):\n'''
replacement='''        low=text.casefold()\n        if low in ("تشغيل الحماية", "تشغيل الحمايه", "الحماية تشغيل", "الحمايه تشغيل"):\n            if not room or not _room_manager(self, room, sender):\n                return True\n            cfg = _save_room_moderation(room, enabled=True)\n            self.send_room_text(room, f"🛡️ تم تشغيل الحماية في الغرفة {room}. حد التكرار: {cfg['repeat_limit']} رسائل.")\n            return True\n        if low in ("إيقاف الحماية", "ايقاف الحماية", "إيقاف الحمايه", "ايقاف الحمايه", "الحماية إيقاف", "الحمايه ايقاف"):\n            if not room or not _room_manager(self, room, sender):\n                return True\n            _save_room_moderation(room, enabled=False)\n            self.send_room_text(room, f"⛔ تم إيقاف الحماية في الغرفة {room}.")\n            return True\n        m_repeat = re.fullmatch(r"mr@(\\d+)", text, re.I)\n        if m_repeat:\n            if not room or not _room_manager(self, room, sender):\n                return True\n            limit = max(2, min(50, int(m_repeat.group(1))))\n            _save_room_moderation(room, repeat_limit=limit)\n            self.send_room_text(room, f"✅ تم ضبط حماية التكرار في {room} على {limit} رسائل متتالية.")\n            return True\n        if low in ("نسخ احتياطي", "نسخه احتياطيه", "backup", "full backup"):\n'''
if needle not in s: raise SystemExit('impl insertion missing')
s=s.replace(needle,replacement,1)

# joining response distinguish blocked room.
old='''            joined = self.join_room(target)\n            self.send_private_text(sender, f"{'✅ تم طلب دخول الغرفة' if joined else '⚠️ الغرفة مسجلة بالفعل'}: {target} | المتصلة فعلياً: {len(self.connected_rooms)}")\n'''
new='''            blocked = _norm_room(target) in getattr(self, "blocked_rooms", set())\n            joined = self.join_room(target)\n            if blocked:\n                reply = f"🚫 البوت محظور من الغرفة {target}. أعطِ البوت إشرافاً أو أونر ثم أعد المحاولة: دخول {target}"\n            else:\n                reply = f"{'✅ تم طلب دخول الغرفة' if joined else '⚠️ الغرفة متصلة بالفعل'}: {target} | المتصلة فعلياً: {len(self.connected_rooms)}"\n            self.send_private_text(sender, reply)\n'''
if old not in s: raise SystemExit('join response missing')
s=s.replace(old,new,1)

# Init repeat tracking.
s=s.replace('''        self.last_messages = defaultdict(list)\n''','''        self.last_messages = defaultdict(list)\n        self._room_repeat_state = defaultdict(lambda: defaultdict(list))\n''',1)

# Replace word filter block with room-aware filter + announcement.
old='''        if self.moderation_enabled and self.banned_words and not _is_master_name(frm):\n            normalized_body = _norm_filter_text(body)\n            hit = next((w for w in self.banned_words if _norm_filter_text(w) and _norm_filter_text(w) in normalized_body), None)\n            if hit:\n                try:\n                    self.send_admin(room, frm, "ban")\n                    self.log("[WORD-FILTER] native room ban", frm, "word=", hit, "room=", room)\n                except Exception as exc:\n                    self.log("[WORD-FILTER] failed:", repr(exc))\n                return\n'''
new='''        room_cfg = _room_moderation_config(room)\n        if room_cfg["enabled"] and not _is_master_name(frm):\n            state = self._room_repeat_state[room][frm]\n            now = time.time(); state[:] = [x for x in state if now - x[0] <= 30.0]\n            state.append((now, body.strip()))\n            same = [x for x in state if x[1] == body.strip()]\n            if len(same) >= room_cfg["repeat_limit"]:\n                self.send_admin(room, frm, "ban")\n                self.send_room_text(room, f"🚫 تم حظر @{frm}\nالسبب: تكرار مشبوه")\n                state.clear()\n                return\n            if len(same) == room_cfg["repeat_limit"] - 1:\n                self.send_room_text(room, f"⚠️ تحذير @{frm}: الرسالة مكررة، الرسالة التالية ستؤدي إلى الحظر.")\n                return\n        filter_words = room_cfg["words"] or (sorted(self.banned_words) if self.moderation_enabled else [])\n        normalized_body = _norm_filter_text(body)\n        hit = next((w for w in filter_words if _norm_filter_text(w) and _norm_filter_text(w) in normalized_body), None)\n        if hit and not _is_master_name(frm):\n            try:\n                self.send_admin(room, frm, "ban")\n                self.send_room_text(room, f"🚫 تم حظر @{frm}\nالسبب: كلمة مسيئة")\n                self.log("[WORD-FILTER] native room ban", frm, "word=", hit, "room=", room)\n            except Exception as exc:\n                self.log("[WORD-FILTER] failed:", repr(exc))\n            return\n'''
if old not in s: raise SystemExit('filter block missing')
s=s.replace(old,new,1)

# Gift renderer accepts receiver photo and makes taller two-avatar panels.
s=s.replace('''def render_gift_card(gift_id, sender_name, receiver_name, sender_photo_url=""):\n''','''def render_gift_card(gift_id, sender_name, receiver_name, sender_photo_url="", receiver_photo_url=""):\n''',1)
old='''    # Two rectangles. The username itself is inside its rectangle; the only\n    # extra text is the small Arabic label above it. Names are rendered from\n    # the raw strings received by the bot, with proper Arabic RTL shaping.\n    box_w=int(w*.64); box_h=int(h*.105); box_x=(w-box_w)//2\n    top_y=int(h*.705); bottom_y=int(h*.815)\n    for y in (top_y,bottom_y):\n        d.rounded_rectangle((box_x,y,box_x+box_w,y+box_h),radius=28,fill=panel,outline=gold,width=4)\n\n    _draw_centered(d,(w/2,top_y+27),"المرسل",25,(255,224,165,255),box_w-20)\n    _draw_centered(d,(w/2,bottom_y+27),"المستلم",25,(255,224,165,255),box_w-20)\n'''
new='''    # Taller sender/receiver panels, each containing its avatar and name.\n    box_w=int(w*.78); box_h=int(h*.125); box_x=(w-box_w)//2\n    top_y=int(h*.675); bottom_y=int(h*.815)\n    for y in (top_y,bottom_y):\n        d.rounded_rectangle((box_x,y,box_x+box_w,y+box_h),radius=32,fill=panel,outline=gold,width=5)\n    for y, label, name, photo in ((top_y, "المرسل", sender_name, sender_photo_url), (bottom_y, "المستلم", receiver_name, receiver_photo_url)):\n        avatar = _load_sender_avatar(photo, 120)\n        if avatar is not None:\n            image.alpha_composite(avatar, (box_x+22, y+(box_h-120)//2)); d=ImageDraw.Draw(image)\n        _draw_centered(d,(box_x+box_w*.62,y+34),label,25,(255,224,165,255),box_w*.60)\n'''
if old not in s: raise SystemExit('gift layout missing')
s=s.replace(old,new,1)
s=s.replace('''            sender_photo_url = self.user_photos.get(sender_name.casefold(), "")\n            gift_path = render_gift_card(gift_id, sender_name, target, sender_photo_url)\n''','''            sender_photo_url = self.user_photos.get(sender_name.casefold(), "")\n            receiver_photo_url = self.user_photos.get(target.casefold().lstrip("@"), "")\n            gift_path = render_gift_card(gift_id, sender_name, target, sender_photo_url, receiver_photo_url)\n''',1)

# Add new commands to help menu page 7.
s=s.replace('''mf@on / mf@off — تشغيل أو إيقاف الفلتر\n''','''تشغيل الحماية / إيقاف الحماية — حماية الغرفة من التكرار\nmr@عدد — ضبط عدد الرسائل المتتالية قبل الحظر\nmf@on / mf@off — تشغيل أو إيقاف الفلتر\n''',1)
p.write_text(s,encoding='utf-8')

m=Path('/home/ubuntu/work/talkin/Talkin1-main/master_bot.py')
t=m.read_text(encoding='utf-8')
t=t.replace('''os.environ["MASTER_SERVICE_ENABLED"] = "1"\n''','''os.environ["MASTER_SERVICE_ENABLED"] = "1"\nos.environ["GROUP_TO_JOIN"] = ""\nos.environ["FIRST_ROOM"] = ""\n''',1)
m.write_text(t,encoding='utf-8')
print('changes applied')
