import io
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage, FlexSendMessage
import google.generativeai as genai
from PIL import Image
import os
from dotenv import load_dotenv

load_dotenv()
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

app = FastAPI()

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LIFF_ID = os.getenv("LIFF_ID")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

DATABASE_URL = "sqlite:///./trip_sharing.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Trip(Base):
    __tablename__ = "trips"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    name = Column(String)
    is_active = Column(Boolean, default=True)
    members = Column(String, default="[]") 
    bills = relationship("Bill", back_populates="trip", cascade="all, delete-orphan")

class Bill(Base):
    __tablename__ = "bills"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    store_name = Column(String)
    amount = Column(Float)
    payer_name = Column(String, nullable=True) 
    split_with = Column(String, default="[]") 
    trip = relationship("Trip", back_populates="bills")

Base.metadata.create_all(bind=engine)

@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id
    db = SessionLocal()
    
    try:
        if user_text.startswith("เริ่มทริป"):
            trip_name = user_text.replace("เริ่มทริป", "").strip()
            if not trip_name:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาพิมพ์ชื่อทริปต่อท้าย เช่น 'เริ่มทริป หัวหิน' นะครับ"))
            else:
                active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
                if active_trip:
                    active_trip.is_active = False
                
                new_trip = Trip(user_id=user_id, name=trip_name, is_active=True, members="[]")
                db.add(new_trip)
                db.commit()
                db.refresh(new_trip)
                
                flex_bubble = {
                    "type": "bubble",
                    "body": {
                        "type": "box", "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "✅ สร้างทริปสำเร็จ!", "weight": "bold", "color": "#06C755", "size": "md"},
                            {"type": "text", "text": f"ทริป: {trip_name}", "weight": "bold", "size": "xl", "margin": "md"},
                            {"type": "text", "text": "กรุณากดปุ่มด้านล่างเพื่อเพิ่มรายชื่อสมาชิกในทริปนี้ครับ", "margin": "md", "wrap": True, "size": "sm"}
                        ]
                    },
                    "footer": {
                        "type": "box", "layout": "vertical",
                        "contents": [{
                            "type": "button", "style": "primary", "color": "#06C755",
                            "action": {
                                "type": "uri", "label": "เพิ่มสมาชิกทริป 👥",
                                "uri": f"https://liff.line.me/{LIFF_ID}?trip_id={new_trip.id}"
                            }
                        }]
                    }
                }
                line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="เพิ่มสมาชิกทริป", contents=flex_bubble))

        elif user_text == "แก้ไขสมาชิก":
            active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
            if not active_trip:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ยังไม่มีทริปที่เปิดอยู่ครับ"))
                return
            
            flex_bubble = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "✏️ จัดการสมาชิกแก๊ง", "weight": "bold", "color": "#007bff", "size": "md"},
                        {"type": "text", "text": f"ทริป: {active_trip.name}", "weight": "bold", "size": "xl", "margin": "md"},
                        {"type": "text", "text": "กดปุ่มด้านล่างเพื่อ เพิ่ม/ลบ รายชื่อเพื่อนร่วมทริปได้เลยครับ", "margin": "md", "wrap": True, "size": "sm"}
                    ]
                },
                "footer": {
                    "type": "box", "layout": "vertical",
                    "contents": [{
                        "type": "button", "style": "primary", "color": "#007bff",
                        "action": {
                            "type": "uri", "label": "แก้ไขรายชื่อ 👥",
                            "uri": f"https://liff.line.me/{LIFF_ID}?trip_id={active_trip.id}"
                        }
                    }]
                }
            }
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="แก้ไขสมาชิกทริป", contents=flex_bubble))

        elif user_text.startswith("เงินสด") or user_text.startswith("บัตรเครดิต"):
            active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
            if not active_trip:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ กรุณาเริ่มทริปก่อนครับ"))
                return
            try:
                parts = user_text.split()
                payment_type = parts[0]
                # 🛠️ ป้องกันบัคพิมพ์ "เงินสด 1,500" โดยการตัดลูกน้ำทิ้งก่อนแปลงค่า
                amount = float(parts[1].replace(',', ''))
                
                new_bill = Bill(trip_id=active_trip.id, store_name=f"{payment_type} (จดมือ)", amount=amount, payer_name=None)
                db.add(new_bill)
                db.commit()
                
                pending_bills = db.query(Bill).filter(Bill.trip_id == active_trip.id, Bill.payer_name == None).all()
                total_bills = len(pending_bills)
                running_total = sum(b.amount for b in pending_bills)

                flex_bubble = {
                    "type": "bubble",
                    "body": {
                        "type": "box", "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "✅ บันทึกยอดจดมือสำเร็จ!", "weight": "bold", "color": "#06C755", "size": "md"},
                            {"type": "text", "text": f"🧾 ประเภท: {payment_type}", "weight": "bold", "size": "lg", "margin": "md"},
                            {"type": "text", "text": f"💰 ยอด: {amount:,.2f} บาท", "size": "md", "margin": "xs"},
                            {"type": "separator", "margin": "md"},
                            {"type": "text", "text": f"🛒 รอบนี้สะสมแล้ว: {total_bills} บิล", "size": "sm", "color": "#666666", "margin": "md"},
                            {"type": "text", "text": f"💵 ยอดรวมรอบนี้: {running_total:,.2f} บาท", "weight": "bold", "size": "md", "margin": "xs"}
                        ]
                    },
                    "footer": {
                        "type": "box", "layout": "vertical",
                        "contents": [{
                            "type": "button", "style": "primary", "color": "#06C755",
                            "action": {
                                "type": "uri", "label": "ปิดรอบบิลนี้ 🛒", "uri": f"https://liff.line.me/{LIFF_ID}?view=close_round&trip_id={active_trip.id}"
                            }
                        }]
                    }
                }
                line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="บันทึกยอดสำเร็จ", contents=flex_bubble))
            except (IndexError, ValueError):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ รูปแบบผิดครับ พิมพ์เว้นวรรค เช่น 'เงินสด 500'"))

        elif user_text == "ปิดรอบบิล":
            active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
            if not active_trip: return
            
            pending_bills = db.query(Bill).filter(Bill.trip_id == active_trip.id, Bill.payer_name == None).all()
            if not pending_bills:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่มีบิลค้างในรอบนี้ครับ ส่งรูปบิลเข้ามาได้เลย"))
                return
            
            round_total = sum(b.amount for b in pending_bills)
            
            flex_bubble = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": f"ทริป: {active_trip.name}", "weight": "bold", "size": "md", "color": "#06C755"},
                        {"type": "text", "text": "ปิดรอบและตั้งค่าบิล 🛒", "weight": "bold", "size": "xl", "margin": "xs"},
                        {"type": "text", "text": f"ยอดรวมสะสมรอบนี้: {round_total:,.2f} บาท", "weight": "bold", "size": "md", "color": "#ff0000", "margin": "md"},
                        {"type": "text", "text": "กรุณากดปุ่มด้านล่างเพื่อเลือกคนจ่ายเงินและเลือกคนร่วมตัวหารในบิลรอบนี้ครับ", "margin": "sm", "size": "sm", "color": "#666666", "wrap": True}
                    ]
                },
                "footer": {
                    "type": "box", "layout": "vertical",
                    "contents": [{
                        "type": "button", "style": "primary", "color": "#06C755",
                        "action": {
                            "type": "uri", "label": "เลือกคนจ่าย & คนหาร 👥",
                            "uri": f"https://liff.line.me/{LIFF_ID}?view=close_round&trip_id={active_trip.id}"
                        }
                    }]
                }
            }
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="ปิดรอบบิล", contents=flex_bubble))

        elif user_text == "สรุปยอดทริป":
            active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
            if not active_trip:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยังไม่มีทริปที่กำลังเปิดอยู่ครับ"))
                return
            
            bills = active_trip.bills
            if not bills:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยังไม่มีบิลในทริปนี้เลยครับ"))
                return
                
            grand_total = sum(b.amount for b in bills)
            members = json.loads(active_trip.members) if active_trip.members else []
            
            paid = {m: 0.0 for m in members}
            owed = {m: 0.0 for m in members}
            
            for b in bills:
                p_name = b.payer_name if b.payer_name else "ยังไม่ระบุคนจ่าย (ค้างปิดรอบ)"
                paid[p_name] = paid.get(p_name, 0.0) + b.amount
                
                b_splitters = json.loads(b.split_with) if b.split_with else members
                if not b_splitters: 
                    b_splitters = members
                
                # 🛠️ ป้องกันบัคหาร 0 
                if len(b_splitters) > 0:
                    b_per_person = b.amount / len(b_splitters)
                    for splitter in b_splitters:
                        owed[splitter] = owed.get(splitter, 0.0) + b_per_person

            balances = {}
            for m in members:
                balances[m] = paid.get(m, 0.0) - owed.get(m, 0.0)

            creditors = []
            debtors = []
            for m, bal in balances.items():
                if bal > 0.01: creditors.append([m, bal])
                elif bal < -0.01: debtors.append([m, abs(bal)])
            
            transfer_text = ""
            while debtors and creditors:
                debtor = debtors[0]
                creditor = creditors[0]
                transfer_amt = min(debtor[1], creditor[1])
                transfer_text += f"💸 {debtor[0]} ➔ โอนให้ {creditor[0]}: {transfer_amt:,.2f} ฿\n"
                
                debtor[1] -= transfer_amt
                creditor[1] -= transfer_amt
                if debtor[1] < 0.01: debtors.pop(0)
                if creditor[1] < 0.01: creditors.pop(0)

            if not transfer_text:
                transfer_text = "✨ ทุกคนเคลียร์ยอดลงตัวเป๊ะ ไม่ต้องมีใครโอนเพิ่มครับ\n"

            summary_text = f"ยอดรวมทริป: {grand_total:,.2f} บาท\n\n👤 รายละเอียดรายบุคคล:\n"
            for m in members:
                summary_text += f"- {m}: ออกก่อน {paid.get(m, 0):,.2f} | ยอดใช้จริง {owed.get(m, 0):,.2f} ฿\n"
            summary_text += f"\n🔄 สรุปแผนการโอนเงิน:\n{transfer_text}"

            flex_bubble = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": f"ทริป: {active_trip.name}", "weight": "bold", "color": "#06C755"},
                        {"type": "text", "text": "สรุปเคลียร์เงินทริปนี้ 🗺️", "weight": "bold", "size": "xl"},
                        {"type": "text", "text": summary_text, "margin": "md", "wrap": True, "size": "sm", "color": "#333333"}
                    ]
                }
            }
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="สรุปยอด", contents=flex_bubble))

        elif user_text == "ล้างบิลทั้งหมด":
            active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
            if active_trip:
                db.query(Bill).filter(Bill.trip_id == active_trip.id).delete()
                db.commit()
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ ล้างตะกร้าบิลทริปนี้เรียบร้อยแล้ว!"))
            
        elif user_text == "จบทริป":
            active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
            if active_trip:
                name = active_trip.name
                active_trip.is_active = False
                db.commit()
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🏁 จบทริป '{name}' เรียบร้อย!"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="คุณยังไม่ได้เริ่มทริปครับ"))

        elif user_text == "ประวัติทริป":
            closed_trips = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == False).order_by(Trip.id.desc()).limit(5).all()
            if not closed_trips:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="📭 คุณยังไม่มีประวัติทริปครับ"))
                return
            history_text = "📚 ประวัติ 5 ทริปล่าสุด:\n"
            for t in closed_trips:
                trip_total = sum(b.amount for b in t.bills)
                history_text += f"\n✈️ {t.name}\n💰 ยอด: {trip_total:,.2f} บาท\n"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=history_text))
            
        elif user_text == "ลบบิลล่าสุด":
            active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
            if active_trip:
                last_bill = db.query(Bill).filter(Bill.trip_id == active_trip.id).order_by(Bill.id.desc()).first()
                if last_bill:
                    deleted_amt = last_bill.amount
                    db.delete(last_bill)
                    db.commit()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🗑️ ย้อนกลับ ลบบิลยอด {deleted_amt} เรียบร้อยแล้ว"))
                    return
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ ไม่มีบิลให้ลบครับ"))

        elif user_text == "คำสั่ง":
            help_text = (
                "🛠️ รายการคำสั่งทั้งหมดสำหรับจัดการทริป:\n\n"
                "1. เริ่มทริป [ชื่อ] : เพื่อเปิดทริปใหม่และตั้งค่าสมาชิกกลุ่ม\n"
                "2. แก้ไขสมาชิก : เพิ่ม/ลด รายชื่อเพื่อนในทริปปัจจุบัน\n"
                "3. ปิดรอบบิล : รวมยอดบิลรอบปัจจุบันเพื่อเลือกคนจ่ายและคนหารบนเว็บ\n"
                "4. สรุปยอดทริป : ดูการคำนวณหักลบกลบหนี้แบบแยกคนละเอียด (ตามส่วนที่กินจริง)\n"
                "5. ลบบิลล่าสุด : ยกเลิกและลบบิลใบสุดท้ายที่เพิ่งบันทึก\n"
                "6. ล้างบิลทั้งหมด : ลบข้อมูลบิลทั้งหมดในทริปปัจจุบันทิ้ง\n"
                "7. จบทริป : ปิดทริปปัจจุบันและเก็บเข้าประวัติระบบ\n"
                "8. ประวัติทริป : เรียกดูสรุปยอดของ 5 ทริปล่าสุดที่จบไปแล้ว\n\n"
                "📝 วิธีบันทึกยอดแบบจดมือ (เงินสด / บัตรเครดิต):\n"
                "- พิมพ์ 'เงินสด [ยอดเงิน]' เช่น: เงินสด 350\n"
                "- พิมพ์ 'บัตรเครดิต [ยอดเงิน]' เช่น: บัตรเครดิต 1200\n\n"
                "📸 คุณสามารถส่งรูปภาพสลิป/ใบเสร็จเข้ามาได้ตลอดเวลา ระบบ AI จะสแกนอ่านยอดเข้าตะกร้าให้โดยอัตโนมัติครับ"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=help_text))

        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="📸 ส่งสลิป หรือพิมพ์ 'เงินสด 100' สะสมยอดได้เลย พอครบร้านแล้วกด 'ปิดรอบบิล' นะครับ"))
    finally:
        db.close()


@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    db = SessionLocal()
    
    try:
        active_trip = db.query(Trip).filter(Trip.user_id == user_id, Trip.is_active == True).first()
        if not active_trip:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="พิมพ์ 'เริ่มทริป [ชื่อ]' ก่อนส่งรูปบิลนะ"))
            return

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🤖 AI กำลังอ่านใบเสร็จ..."))
        
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b"".join([chunk for chunk in message_content.iter_content()])
        img = Image.open(io.BytesIO(image_bytes))
        
        # 🛠️ ปรับ Prompt ให้ Gemini ห้ามใส่ลูกน้ำเด็ดขาด
        prompt = """อ่านข้อความจากรูปใบเสร็จ ตอบเป็น JSON: {"store":"ชื่อร้าน","total":ยอดรวม} (ส่วนของ total ให้ตอบตัวเลขล้วนๆ ห้ามใส่ลูกน้ำเด็ดขาด)"""
        response = model.generate_content([prompt, img])
        result_text = response.text.strip().replace("```json", "").replace("```", "")
        
        receipt_data = json.loads(result_text)
        store_name = receipt_data.get('store', 'ไม่ระบุชื่อร้าน')
        
        # 🛠️ ป้องกันชั้นที่ 2: ล้างลูกน้ำด้วย Python อีกทีก่อนแปลงค่า
        raw_total = str(receipt_data.get('total', 0)).replace(',', '').strip()
        try:
            bill_total = float(raw_total)
        except ValueError:
            bill_total = 0.0

        new_bill = Bill(trip_id=active_trip.id, store_name=store_name, amount=bill_total, payer_name=None)
        db.add(new_bill)
        db.commit()
        
        pending_bills = db.query(Bill).filter(Bill.trip_id == active_trip.id, Bill.payer_name == None).all()
        total_bills = len(pending_bills)
        running_total = sum(b.amount for b in pending_bills)

        flex_bubble = {
            "type": "bubble",
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "✅ AI บันทึกใบเสร็จสำเร็จ!", "weight": "bold", "color": "#06C755", "size": "md"},
                    {"type": "text", "text": f"🧾 ร้าน: {store_name}", "weight": "bold", "size": "lg", "margin": "md"},
                    {"type": "text", "text": f"💰 ยอด: {bill_total:,.2f} บาท", "size": "md", "margin": "xs"},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": f"🛒 รอบนี้สะสมแล้ว: {total_bills} บิล", "size": "sm", "color": "#666666", "margin": "md"},
                    {"type": "text", "text": f"💵 ยอดรวมรอบนี้: {running_total:,.2f} บาท", "weight": "bold", "size": "md", "margin": "xs"}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [{
                    "type": "button", "style": "primary", "color": "#06C755",
                    "action": {
                        "type": "uri", "label": "ปิดรอบบิลนี้ 🛒", "uri": f"https://liff.line.me/{LIFF_ID}?view=close_round&trip_id={active_trip.id}"
                    }
                }]
            }
        }
        line_bot_api.push_message(user_id, FlexSendMessage(alt_text="บันทึกบิลสำเร็จ", contents=flex_bubble))
    except Exception as e:
        line_bot_api.push_message(user_id, TextSendMessage(text=f"เกิดข้อผิดพลาด: {str(e)}"))
    finally:
        db.close()

# ---------------------------------------------------------
# ส่วนของ API และ หน้าเว็บ LIFF (เหมือนเดิม 100%)
# ---------------------------------------------------------
class MemberData(BaseModel):
    trip_id: int
    members: list

class CloseRoundData(BaseModel):
    trip_id: int
    payer: str
    split_with: list

@app.get("/api/get_members")
async def get_members(trip_id: int):
    db = SessionLocal()
    try:
        trip = db.query(Trip).filter(Trip.id == trip_id).first()
        pending_bills = db.query(Bill).filter(Bill.trip_id == trip_id, Bill.payer_name == None).all()
        round_total = sum(b.amount for b in pending_bills)
        
        members_list = json.loads(trip.members) if trip and trip.members else []
        return {"members": members_list, "round_total": round_total}
    finally:
        db.close()

@app.post("/api/set_members")
async def set_members(data: MemberData):
    db = SessionLocal()
    try:
        trip = db.query(Trip).filter(Trip.id == data.trip_id).first()
        if trip:
            trip.members = json.dumps(data.members)
            db.commit()
            line_bot_api.push_message(trip.user_id, TextSendMessage(text=f"👥 อัปเดตรายชื่อเป็น {len(data.members)} คนเรียบร้อยแล้วครับ!"))
        return {"status": "success"}
    finally:
        db.close()

@app.post("/api/close_round")
async def close_round(data: CloseRoundData):
    db = SessionLocal()
    try:
        trip = db.query(Trip).filter(Trip.id == data.trip_id).first()
        if not trip: return {"status": "error", "message": "Trip not found"}
        
        pending_bills = db.query(Bill).filter(Bill.trip_id == data.trip_id, Bill.payer_name == None).all()
        round_total = sum(b.amount for b in pending_bills)
        
        for b in pending_bills:
            b.payer_name = data.payer
            b.split_with = json.dumps(data.split_with) 
        db.commit()
        
        msg = (f"✅ ปิดรอบบิลสำเร็จ!\n"
               f"👤 คนจ่าย: {data.payer}\n"
               f"💰 ยอดรวม: {round_total:,.2f} บาท\n"
               f"👥 คนร่วมหาร ({len(data.split_with)} คน): {', '.join(data.split_with)}\n\n"
               f"👉 สมาชิกกลุ่มส่งสลิปรอบใหม่ต่อได้เลยครับ!")
        line_bot_api.push_message(trip.user_id, TextSendMessage(text=msg))
        return {"status": "success"}
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
async def serve_liff_page():
    html_content = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>จัดการทริป</title>
        <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
        <style>
            body {{ font-family: 'Kanit', sans-serif; padding: 20px; background-color: #f7f7f7; margin: 0; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .input-group {{ display: flex; gap: 10px; margin-top: 15px; }}
            input[type="text"] {{ flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 8px; font-size: 16px; }}
            button {{ padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; color: white; }}
            .btn-add {{ background-color: #007bff; }}
            .btn-save {{ background-color: #06C755; width: 100%; margin-top: 25px; padding: 12px; }}
            .member-tag {{ display: inline-flex; align-items: center; gap: 8px; background: #e0f0ff; padding: 8px 12px; border-radius: 20px; margin: 5px; color: #007bff; font-weight: bold; }}
            .btn-remove {{ background: none; border: none; color: #ff4d4f; font-weight: bold; cursor: pointer; padding: 0; font-size: 14px; }}
            .section {{ margin-top: 20px; padding-top: 15px; border-top: 1px solid #eee; }}
            label {{ display: block; margin: 12px 0; font-size: 16px; cursor: pointer; }}
            input[type="radio"], input[type="checkbox"] {{ transform: scale(1.2); margin-right: 10px; }}
        </style>
    </head>
    <body>
        <div class="card" id="view-members" style="display: none;">
            <h2>ตั้งค่าสมาชิกแก๊งทริป 🏕️</h2>
            <div class="input-group">
                <input type="text" id="member-name" placeholder="พิมพ์ชื่อเพื่อน..." onkeypress="if(event.key === 'Enter') addMember()">
                <button class="btn-add" onclick="addMember()">เพิ่ม</button>
            </div>
            <div id="member-list" style="margin-top: 20px;"></div>
            <button class="btn-save" onclick="saveMembers()">บันทึกรายชื่อ</button>
        </div>

        <div class="card" id="view-close-round" style="display: none;">
            <h2>ปิดรอบบิล & ตั้งค่าตัวหาร 🛒</h2>
            <h3 style="color: #ff4d4f; margin-bottom: 5px;">ยอดรวมรอบนี้: <span id="round-amount">0.00</span> บาท</h3>
            
            <div class="section">
                <strong>👤 1. ใครเป็นคนสำรองจ่ายเงินรอบนี้?</strong>
                <div id="payer-options" style="margin-top: 10px;"></div>
            </div>

            <div class="section">
                <strong>👥 2. บิลรอบนี้ใครร่วมหารบ้าง? (ค่าเริ่มต้นเลือกทุกคน)</strong>
                <div id="splitter-options" style="margin-top: 10px;"></div>
            </div>

            <button class="btn-save" onclick="submitCloseRound()">บันทึกการปิดรอบบิล</button>
        </div>

        <script>
            let members = [];
            let tripId = null;
            let currentView = "members";

            async function init() {{
                await liff.init({{ liffId: "{LIFF_ID}" }});
                const params = new URLSearchParams(window.location.search);
                tripId = params.get("trip_id");
                const viewParam = params.get("view");
                
                if (viewParam === "close_round") {{
                    currentView = "close_round";
                    document.getElementById("view-close-round").style.display = "block";
                }} else {{
                    currentView = "members";
                    document.getElementById("view-members").style.display = "block";
                }}
                
                if (tripId) {{
                    const res = await fetch(`/api/get_members?trip_id=${{tripId}}`);
                    const data = await res.json();
                    if (data.members) {{
                        members = data.members;
                        if (currentView === "members") {{
                            renderMembers();
                        }} else if (currentView === "close_round") {{
                            document.getElementById("round-amount").innerText = parseFloat(data.round_total).toLocaleString('th-TH', {{minimumFractionDigits: 2}});
                            renderCloseRoundOptions();
                        }}
                    }}
                }}
            }}
            init();

            function addMember() {{
                const input = document.getElementById("member-name");
                const name = input.value.trim();
                if (name && !members.includes(name)) {{
                    members.push(name);
                    renderMembers();
                }}
                input.value = "";
            }}

            function removeMember(index) {{
                members.splice(index, 1);
                renderMembers();
            }}

            function renderMembers() {{
                const container = document.getElementById("member-list");
                container.innerHTML = "<strong>สมาชิกปัจจุบัน:</strong><br>";
                if (members.length === 0) {{
                    container.innerHTML += "<span style='color:#999; font-size:14px;'>ยังไม่มีสมาชิก</span>";
                }} else {{
                    members.forEach((m, index) => {{
                        container.innerHTML += `
                            <span class="member-tag">
                                ${{m}} <button class="btn-remove" onclick="removeMember(${{index}})">✖</button>
                            </span>`;
                    }});
                }}
            }}

            async function saveMembers() {{
                if (members.length === 0) {{ alert("กรุณาเพิ่มสมาชิกอย่างน้อย 1 คนครับ"); return; }}
                if (!tripId) return;
                await fetch('/api/set_members', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ trip_id: parseInt(tripId), members: members }})
                }});
                liff.closeWindow();
            }}

            function renderCloseRoundOptions() {{
                const payerContainer = document.getElementById("payer-options");
                const splitterContainer = document.getElementById("splitter-options");
                
                payerContainer.innerHTML = "";
                splitterContainer.innerHTML = "";
                
                if (members.length === 0) {{
                    payerContainer.innerHTML = "<span style='color:red;'>ไม่พบรายชื่อสมาชิก กลุ่มนี้ยังไม่ได้เพิ่มเพื่อนร่วมทริป</span>";
                    return;
                }}

                members.forEach((m, index) => {{
                    const payerChecked = index === 0 ? "checked" : "";
                    payerContainer.innerHTML += `
                        <label>
                            <input type="radio" name="round_payer" value="${{m}}" ${{payerChecked}}> ${{m}}
                        </label>`;
                    
                    splitterContainer.innerHTML += `
                        <label>
                            <input type="checkbox" name="round_splitters" value="${{m}}" checked> ${{m}}
                        </label>`;
                }});
            }}

            async function submitCloseRound() {{
                const payerEl = document.querySelector('input[name="round_payer"]:checked');
                if (!payerEl) {{ alert("กรุณาเลือกคนสำรองจ่ายเงินรอบนี้ด้วยครับ"); return; }}
                const payer = payerEl.value;

                const splitterCheckboxes = document.querySelectorAll('input[name="round_splitters"]:checked');
                const splitWith = Array.from(splitterCheckboxes).map(cb => cb.value);
                
                if (splitWith.length === 0) {{ alert("กรุณาเลือกคนร่วมหารอย่างน้อย 1 คนครับ"); return; }}
                if (!tripId) return;

                await fetch('/api/close_round', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        trip_id: parseInt(tripId),
                        payer: payer,
                        split_with: splitWith
                    }})
                }});
                liff.closeWindow();
            }}
        </script>
    </body>
    </html>
    """
    return html_content