import streamlit as st
import uuid
from datetime import datetime
from groq import Groq
from supabase import create_client, Client
import os
import hashlib
import json
import pandas as pd

st.set_page_config(page_title="Anchorpoint Navigator", page_icon="⚓", layout="wide")

# ========== BRANDING CSS ==========
st.markdown("""
<style>
    .stApp { background-color: #e9ecef; }
    [data-testid="stSidebar"] {
        background-color: #1a3e60;
        padding-top: 2rem;
    }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    [data-testid="stSidebar"] button:hover { background-color: #2c5a7a !important; }
    h1, h2, h3, .stMarkdown, .stCaption { color: #1a3e60; }
    a { color: #d4af37; }
    .stButton button {
        background-color: #1a3e60;
        color: white;
        border-radius: 8px;
    }
    .stButton button:hover { background-color: #2c5a7a; }
    .stAlert { border-left-color: #d4af37; }
    [data-testid="stChatMessage"] {
        background-color: #ffffff !important;
        color: #111111 !important;
        border-radius: 12px;
        padding: 10px;
        margin-bottom: 8px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    [data-testid="stChatMessage"][data-testid*="assistant"] {
        background-color: #f8f9fa !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚓ Anchorpoint AI Navigator")
st.caption("Diagnosing operational gaps. Stewarding certainty.")

# ========== LOAD SECRETS ==========
SUPABASE_URL = st.secrets["https://iiasatjvwfvkswfqgadg.supabase.co"]
SUPABASE_ANON_KEY = st.secrets["sb_publishable_yJ0piTKI03yBVuNvoqlzxA_JeF27QU9"]
GROQ_API_KEY = st.secrets["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"]
APP_URL = st.secrets.get("https://anchorpoint-navigator.streamlit.app")
STEWARD_EMAIL = "anchorpointoptimum@gmail.com" 

# ========== INIT CLIENTS ==========
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

# ========== LOAD KNOWLEDGE FILE ==========
with open("Anchorpoint_AI_Knowledge.txt", "r") as f:
    system_content = f.read()

# ========== SESSION STATE INIT ==========
if "auth_user" not in st.session_state:
    st.session_state.auth_user = None
if "guest_mode" not in st.session_state:
    st.session_state.guest_mode = True
if "current_conv_id" not in st.session_state:
    st.session_state.current_conv_id = None
if "conversations_list" not in st.session_state:
    st.session_state.conversations_list = []
if "messages" not in st.session_state:
    st.session_state.messages = []
if "edit_msg_id" not in st.session_state:
    st.session_state.edit_msg_id = None
if "editing_title_id" not in st.session_state:
    st.session_state.editing_title_id = None
if "show_observatory" not in st.session_state:
    st.session_state.show_observatory = False

# ========== HELPER FUNCTIONS ==========
def friendly_error(user_message: str):
    st.error(f"⚠️ {user_message}")

def login_user(email, password):
    try:
        resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.auth_user = resp.user
        st.session_state.guest_mode = False
        ensure_profile_exists()
        load_user_conversations()
        return True
    except Exception:
        friendly_error("Unable to sign in. Check your email and password, then try again.")
        return False

def signup_user(email, password):
    try:
        resp = supabase.auth.sign_up({"email": email, "password": password})
        st.session_state.auth_user = resp.user
        st.session_state.guest_mode = False
        ensure_profile_exists()
        load_user_conversations()
        return True
    except Exception:
        friendly_error("Signup failed. The email may already be registered, or the password is too weak.")
        return False

def ensure_profile_exists():
    if not st.session_state.auth_user:
        return
    try:
        resp = supabase.table("profiles").select("id").eq("id", st.session_state.auth_user.id).execute()
        if not resp.data:
            supabase.table("profiles").insert({
                "id": st.session_state.auth_user.id,
                "email": st.session_state.auth_user.email,
                "full_name": st.session_state.auth_user.user_metadata.get("full_name", "")
            }).execute()
    except Exception:
        pass

def logout_user():
    supabase.auth.sign_out()
    st.session_state.auth_user = None
    st.session_state.guest_mode = True
    st.session_state.current_conv_id = None
    st.session_state.messages = []
    st.session_state.show_observatory = False
    st.rerun()

def load_user_conversations():
    if not st.session_state.auth_user:
        return
    try:
        resp = supabase.table("conversations").select("*").eq("user_id", st.session_state.auth_user.id).order("updated_at", desc=True).execute()
        st.session_state.conversations_list = resp.data
        if st.session_state.conversations_list and not st.session_state.current_conv_id:
            st.session_state.current_conv_id = st.session_state.conversations_list[0]["id"]
            load_conversation_messages(st.session_state.current_conv_id)
        elif not st.session_state.conversations_list:
            create_new_conversation()
    except Exception:
        friendly_error("Could not load your conversation history. Refresh the page.")
        st.session_state.conversations_list = []

def load_conversation_messages(conv_id):
    try:
        resp = supabase.table("messages").select("*").eq("conversation_id", conv_id).order("created_at", asc=True).execute()
        messages = [{"role": m["role"], "content": m["content"], "id": m["id"], "parent_id": m.get("parent_id")} for m in resp.data]
        if not messages or messages[0]["role"] != "system":
            system_msg = {"role": "system", "content": system_content + "\n\nRemember: You are a Navigator. Lead with questions.", "id": str(uuid.uuid4())}
            messages.insert(0, system_msg)
        st.session_state.messages = messages
        st.session_state.current_conv_id = conv_id
    except Exception:
        friendly_error("Unable to load conversation. Please try refreshing.")

def create_new_conversation():
    system_msg_content = system_content + "\n\nRemember: You are a Navigator. Lead with questions."
    opening_assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": (
            "I'm Anchorpoint's Navigator. I collect intelligence about operational reality. "
            "Describe a process or challenge – I'll listen for gaps, surface governance signals, and document this conversation as a field log entry.\n\n"
            "What work‑as‑imagined vs. work‑as‑done gap would you like to explore?"
        ),
        "parent_id": None
    }

    if st.session_state.auth_user:
        try:
            new_conv = {
                "user_id": st.session_state.auth_user.id,
                "title": "New conversation",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            resp = supabase.table("conversations").insert(new_conv).execute()
            conv_id = resp.data[0]["id"]
            supabase.table("messages").insert({
                "conversation_id": conv_id,
                "role": "system",
                "content": system_msg_content
            }).execute()
            supabase.table("messages").insert({
                "conversation_id": conv_id,
                "role": "assistant",
                "content": opening_assistant_msg["content"]
            }).execute()
            st.session_state.messages = [
                {"role": "system", "content": system_msg_content, "id": str(uuid.uuid4())},
                opening_assistant_msg
            ]
            st.session_state.current_conv_id = conv_id
            load_user_conversations()
        except Exception:
            friendly_error("Unable to start a new conversation. You can still chat in guest mode.")
            st.session_state.messages = [
                {"role": "system", "content": system_msg_content, "id": str(uuid.uuid4())},
                opening_assistant_msg
            ]
            st.session_state.current_conv_id = None
    else:
        st.session_state.messages = [
            {"role": "system", "content": system_msg_content, "id": str(uuid.uuid4())},
            opening_assistant_msg
        ]
        st.session_state.current_conv_id = None
    st.rerun()

def delete_conversation(conv_id):
    if st.session_state.auth_user:
        try:
            supabase.table("conversations").delete().eq("id", conv_id).execute()
            load_user_conversations()
            if st.session_state.current_conv_id == conv_id:
                if st.session_state.conversations_list:
                    st.session_state.current_conv_id = st.session_state.conversations_list[0]["id"]
                    load_conversation_messages(st.session_state.current_conv_id)
                else:
                    create_new_conversation()
        except Exception:
            friendly_error("Could not delete conversation. It may have been already removed.")
        st.rerun()

def switch_conversation(conv_id):
    load_conversation_messages(conv_id)
    st.rerun()

def update_conversation_title(conv_id, title):
    if st.session_state.auth_user:
        try:
            supabase.table("conversations").update({"title": title, "updated_at": datetime.now().isoformat()}).eq("id", conv_id).execute()
            load_user_conversations()
        except Exception:
            friendly_error("Could not update title.")

def save_conversation_messages(conv_id, messages_list):
    if st.session_state.auth_user:
        try:
            supabase.table("messages").delete().eq("conversation_id", conv_id).execute()
            for msg in messages_list:
                if msg["role"] == "system":
                    continue
                supabase.table("messages").insert({
                    "conversation_id": conv_id,
                    "role": msg["role"],
                    "content": msg["content"],
                    "parent_id": msg.get("parent_id")
                }).execute()
            supabase.table("conversations").update({"updated_at": datetime.now().isoformat()}).eq("id", conv_id).execute()
        except Exception:
            friendly_error("Your conversation may not have been saved. You can still continue, but progress might be lost on refresh.")

def get_assistant_response(messages_list):
    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages_list if m["role"] != "system"]
    system_msg = next((m for m in messages_list if m["role"] == "system"), None)
    full_messages = []
    if system_msg:
        full_messages.append({"role": "system", "content": system_msg["content"]})
    full_messages.extend(api_messages)
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=full_messages,
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception:
        friendly_error("The AI service is temporarily unavailable. Please try again in a moment.")
        return "I'm having trouble responding right now. Please refresh or try again later."

def generate_share_token(conv_id):
    resp = supabase.table("conversations").select("share_token").eq("id", conv_id).execute()
    if resp.data and resp.data[0].get("share_token"):
        return resp.data[0]["share_token"]
    else:
        token = hashlib.sha256(f"{conv_id}{uuid.uuid4()}".encode()).hexdigest()[:16]
        supabase.table("conversations").update({"share_token": token}).eq("id", conv_id).execute()
        return token

def save_registry_entry(conv_id, summary_text, conversation_text):
    """Parse summary, calculate GAS score and leakage estimate, then save."""
    if not st.session_state.auth_user:
        return False
    
    # Step 1: Extract structured fields from summary
    extraction_prompt = f"""Extract the following fields from this Anchorpoint Navigator summary. Return ONLY valid JSON, no extra text.

Summary:
{summary_text}

Required fields:
- gap_type: one of (E, K, SC, CD, WE)
- key_insight: one sentence
- persistence_driver: short phrase
- suggested_action: short phrase
- linked_asset: string

Example response:
{{"gap_type": "SC", "key_insight": "WhatsApp approvals replace formal system", "persistence_driver": "no delegated authority", "suggested_action": "install delegate rule", "linked_asset": "Nigerian Process Library"}}
"""

    try:
        resp1 = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": extraction_prompt}],
            temperature=0.2,
            max_tokens=300
        )
        result = resp1.choices[0].message.content
        result = result.replace("```json", "").replace("```", "").strip()
        data = json.loads(result)
        
        # Step 2: Quantify GAS and leakage based on full conversation
        quantification_prompt = f"""Based on this conversation, estimate:
1. A GAS score (0-100) where 0=chaotic, 100=fully governed. Use: gap type severity (E=70, K=80, SC=40, CD=30, WE=20), persistence driver severity, and user's tone.
2. An estimated off‑platform approval leakage percentage (0-100).

Return ONLY JSON: {{"gas_score": number, "leakage_estimate": number}}

Conversation:
{conversation_text}
"""
        resp2 = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": quantification_prompt}],
            temperature=0.2,
            max_tokens=100
        )
        q_result = resp2.choices[0].message.content
        q_result = q_result.replace("```json", "").replace("```", "").strip()
        q_data = json.loads(q_result)
        
        # Insert into registry_entries
        supabase.table("registry_entries").insert({
            "conversation_id": conv_id,
            "gap_type": data.get("gap_type"),
            "key_insight": data.get("key_insight"),
            "persistence_driver": data.get("persistence_driver"),
            "suggested_action": data.get("suggested_action"),
            "linked_asset": data.get("linked_asset"),
            "gas_score": q_data.get("gas_score"),
            "leakage_estimate": q_data.get("leakage_estimate")
        }).execute()
        return True
    except Exception as e:
        print(f"Registry save error: {e}")
        return False

def show_observatory():
    st.subheader("🔭 Operational Intelligence Observatory")
    st.caption("Aggregated insights from all registry entries")
    
    try:
        entries = supabase.table("registry_entries").select("*").execute()
        df = pd.DataFrame(entries.data)
        
        if not df.empty:
            # Gap type distribution
            st.subheader("Gap Type Distribution")
            gap_counts = df['gap_type'].value_counts().reset_index()
            gap_counts.columns = ['Gap Type', 'Count']
            st.bar_chart(gap_counts.set_index('Gap Type'))
            
            # Top persistence drivers
            st.subheader("Top Persistence Drivers")
            driver_counts = df['persistence_driver'].value_counts().head(5).reset_index()
            driver_counts.columns = ['Driver', 'Count']
            st.dataframe(driver_counts)
            
            # Most referenced assets
            st.subheader("Most Referenced Assets")
            asset_counts = df['linked_asset'].value_counts().head(5).reset_index()
            asset_counts.columns = ['Asset', 'Count']
            st.dataframe(asset_counts)
            
            # Timeline
            st.subheader("Entries Over Time")
            df['date'] = pd.to_datetime(df['created_at']).dt.date
            timeline = df.groupby('date').size().reset_index(name='count')
            st.line_chart(timeline.set_index('date'))
            
            # GAS score distribution (Layer 4)
            st.subheader("GAS Score Distribution")
            gas_data = df[df['gas_score'].notna()]
            if not gas_data.empty:
                avg_gas = gas_data['gas_score'].mean()
                st.metric("Average GAS Score", f"{avg_gas:.1f}")
                # Simple histogram: count per decile
                gas_data['decile'] = (gas_data['gas_score'] // 10) * 10
                decile_counts = gas_data['decile'].value_counts().sort_index().reset_index()
                decile_counts.columns = ['GAS Score Range', 'Count']
                st.bar_chart(decile_counts.set_index('GAS Score Range'))
            
            # Leakage estimate distribution
            st.subheader("Estimated Off‑platform Leakage")
            leak_data = df[df['leakage_estimate'].notna()]
            if not leak_data.empty:
                avg_leak = leak_data['leakage_estimate'].mean()
                st.metric("Average Leakage", f"{avg_leak:.1f}%")
                leak_data['leak_bucket'] = (leak_data['leakage_estimate'] // 10) * 10
                leak_counts = leak_data['leak_bucket'].value_counts().sort_index().reset_index()
                leak_counts.columns = ['Leakage % Range', 'Count']
                st.bar_chart(leak_counts.set_index('Leakage % Range'))
            
            # Raw data toggle
            if st.checkbox("Show raw data"):
                st.dataframe(df)
        else:
            st.info("No registry entries yet. Generate summaries to see intelligence.")
    except Exception as e:
        st.error(f"Could not load observatory data: {e}")
    
    if st.button("← Back to Navigator"):
        st.session_state.show_observatory = False
        st.rerun()

# ========== HANDLE SHARED CONVERSATION VIEW ==========
query_params = st.query_params
share_token = query_params.get("share")
if share_token:
    conv_resp = supabase.table("conversations").select("id").eq("share_token", share_token).execute()
    if conv_resp.data:
        conv_id = conv_resp.data[0]["id"]
        msgs_resp = supabase.table("messages").select("*").eq("conversation_id", conv_id).order("created_at", asc=True).execute()
        st.subheader("📄 Shared Conversation (Read-Only)")
        for msg in msgs_resp.data:
            if msg["role"] != "system":
                st.chat_message(msg["role"]).write(msg["content"])
        st.caption("This is a read-only view. To continue the conversation, please sign in.")
        st.stop()
    else:
        st.error("Invalid share link.")
        st.stop()

# ========== OBSERVATORY DASHBOARD ==========
if st.session_state.show_observatory:
    show_observatory()
    st.stop()

# ========== SIDEBAR ==========
with st.sidebar:
    st.image("https://raw.githubusercontent.com/anchorpointoptimum-cmd/anchorpoint_navigation_supabase/main/anchorpoint_logo.jpeg", use_container_width=True)
    st.markdown("---")

    if st.session_state.auth_user:
        st.write(f"👤 {st.session_state.auth_user.email}")
        if st.button("Logout"):
            logout_user()
    else:
        st.markdown("### 🔐 Account")
        tab1, tab2 = st.tabs(["Login", "Sign up"])
        with tab1:
            st.markdown("**Email / Password**")
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            if st.button("Login", key="login_btn"):
                if login_email and login_password:
                    login_user(login_email, login_password)
                else:
                    friendly_error("Please enter both email and password.")
            st.markdown("---")
            st.markdown("**Or continue with**")
            auth_url = supabase.auth.sign_in_with_oauth(
                {"provider": "google", "options": {"redirect_to": APP_URL}}
            ).url
            st.link_button("🔐 Continue with Google", url=auth_url)
        with tab2:
            signup_email = st.text_input("Email", key="signup_email")
            signup_password = st.text_input("Password", type="password", key="signup_password")
            if st.button("Sign up", key="signup_btn"):
                if signup_email and signup_password:
                    signup_user(signup_email, signup_password)
                else:
                    friendly_error("Please enter an email and a password (at least 6 characters).")

    st.divider()
    st.markdown("### 📜 Intelligence Log")
    if st.button("➕ New conversation", use_container_width=True):
        create_new_conversation()

    if st.session_state.auth_user:
        for conv in st.session_state.conversations_list:
            conv_id = conv["id"]
            is_editing = (st.session_state.editing_title_id == conv_id)
            cols = st.columns([0.6, 0.15, 0.15, 0.1])
            with cols[0]:
                if is_editing:
                    new_title = st.text_input("Title", value=conv["title"], key=f"edit_title_{conv_id}", label_visibility="collapsed")
                    if st.button("💾 Save", key=f"save_title_{conv_id}"):
                        if new_title.strip():
                            update_conversation_title(conv_id, new_title.strip())
                            st.session_state.editing_title_id = None
                            st.rerun()
                        else:
                            friendly_error("Title cannot be empty.")
                    if st.button("Cancel", key=f"cancel_title_{conv_id}"):
                        st.session_state.editing_title_id = None
                        st.rerun()
                else:
                    display_title = conv["title"][:30] + ("..." if len(conv["title"]) > 30 else "")
                    if st.button(display_title, key=f"conv_{conv_id}", use_container_width=True):
                        switch_conversation(conv_id)
            with cols[1]:
                if not is_editing:
                    if st.button("✏️", key=f"rename_{conv_id}"):
                        st.session_state.editing_title_id = conv_id
                        st.rerun()
            with cols[2]:
                if not is_editing:
                    if st.button("🔗", key=f"share_{conv_id}"):
                        token = generate_share_token(conv_id)
                        share_url = f"{APP_URL}?share={token}"
                        st.info(f"Shareable link: {share_url}")
                        st.code(share_url, language="text")
            with cols[3]:
                if not is_editing:
                    if st.button("🗑️", key=f"del_{conv_id}"):
                        delete_conversation(conv_id)
            st.caption(conv.get("updated_at", conv["created_at"])[:10])

        st.divider()
        st.markdown("### 📋 Registry Intelligence")
        try:
            if st.session_state.current_conv_id:
                entries = supabase.table("registry_entries").select("*").eq("conversation_id", st.session_state.current_conv_id).execute()
                if entries.data:
                    for entry in entries.data[:3]:
                        st.caption(f"**{entry['gap_type']}** – {entry['key_insight'][:60]}..." if entry.get('key_insight') else f"**{entry['gap_type']}**")
                    if len(entries.data) > 3:
                        st.caption("*More entries available*")
                else:
                    st.caption("No registry entries yet. Generate a summary to create one.")
            else:
                st.caption("Select a conversation to see its registry entries.")
        except Exception:
            st.caption("Registry loading...")
        
        # Observatory button for steward only
        if st.session_state.auth_user.email == STEWARD_EMAIL:
            st.divider()
            st.markdown("### 🔭 Observatory")
            if st.button("📊 View Intelligence Dashboard"):
                st.session_state.show_observatory = True
                st.rerun()
    else:
        st.info("💡 Sign in to save conversations and contribute to your governance profile.")
        if st.session_state.messages:
            st.caption("Guest session (intelligence not persisted)")

# ========== MAIN CHAT AREA ==========
if st.session_state.messages:
    for msg in st.session_state.messages:
        if msg["role"] == "system":
            continue
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "user":
                if st.button("✏️", key=f"edit_{msg['id']}"):
                    st.session_state.edit_msg_id = msg["id"]
                    st.rerun()
else:
    if not st.session_state.messages:
        create_new_conversation()
        st.rerun()

# Edit modal
if st.session_state.edit_msg_id:
    msg_to_edit = next((m for m in st.session_state.messages if m.get("id") == st.session_state.edit_msg_id), None)
    if msg_to_edit:
        with st.form(key="edit_form"):
            new_content = st.text_area("Edit your message:", value=msg_to_edit["content"])
            if st.form_submit_button("Save and regenerate"):
                msg_to_edit["content"] = new_content
                idx = st.session_state.messages.index(msg_to_edit)
                st.session_state.messages = st.session_state.messages[:idx+1]
                new_reply = get_assistant_response(st.session_state.messages)
                assistant_msg = {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": new_reply,
                    "parent_id": msg_to_edit["id"]
                }
                st.session_state.messages.append(assistant_msg)
                if st.session_state.auth_user and st.session_state.current_conv_id:
                    save_conversation_messages(st.session_state.current_conv_id, st.session_state.messages)
                user_msgs = [m for m in st.session_state.messages if m["role"] == "user"]
                if len(user_msgs) == 1 and st.session_state.auth_user:
                    title = user_msgs[0]["content"][:40] + ("..." if len(user_msgs[0]["content"]) > 40 else "")
                    update_conversation_title(st.session_state.current_conv_id, title)
                st.session_state.edit_msg_id = None
                st.rerun()
    if st.button("Cancel edit"):
        st.session_state.edit_msg_id = None
        st.rerun()

# Chat input
if not st.session_state.edit_msg_id:
    if prompt := st.chat_input("Describe an operational process or challenge..."):
        user_msg = {"id": str(uuid.uuid4()), "role": "user", "content": prompt}
        st.session_state.messages.append(user_msg)
        with st.spinner("Diagnosing..."):
            reply = get_assistant_response(st.session_state.messages)
        assistant_msg = {"id": str(uuid.uuid4()), "role": "assistant", "content": reply, "parent_id": user_msg["id"]}
        st.session_state.messages.append(assistant_msg)

        if st.session_state.auth_user:
            if not st.session_state.current_conv_id:
                create_new_conversation()
            else:
                save_conversation_messages(st.session_state.current_conv_id, st.session_state.messages)
                user_msgs = [m for m in st.session_state.messages if m["role"] == "user"]
                if len(user_msgs) == 1:
                    title = user_msgs[0]["content"][:40] + ("..." if len(user_msgs[0]["content"]) > 40 else "")
                    update_conversation_title(st.session_state.current_conv_id, title)
                load_user_conversations()
        else:
            if len([m for m in st.session_state.messages if m["role"] == "user"]) == 1:
                st.info("💡 You're in guest mode. Create an account to add this conversation to your governance profile.")
        st.rerun()

# Summary generation with registry save (Layer 2 + Layer 4)
assistant_msgs = [m for m in st.session_state.messages if m["role"] == "assistant"]
if len(assistant_msgs) >= 3 and "summary_shown" not in st.session_state:
    st.divider()
    if st.button("📋 Generate Summary"):
        conv_text = ""
        for m in st.session_state.messages:
            if m["role"] != "system":
                conv_text += f"{m['role'].upper()}: {m['content']}\n\n"
        with st.spinner("Generating summary..."):
            summary_response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "Generate a brief operational gap summary with exactly these sections: Gap Type, Key Insight, Suggested First Step, Relevant Asset. Use markdown bullets."},
                    {"role": "user", "content": f"Conversation:\n{conv_text}"}
                ],
                temperature=0.3,
                max_tokens=300
            )
            summary = summary_response.choices[0].message.content
            st.session_state.summary = summary
            st.session_state.summary_shown = True
            
            # Save to Registry Intelligence (Layer 2 + Layer 4)
            if st.session_state.auth_user and st.session_state.current_conv_id:
                save_registry_entry(st.session_state.current_conv_id, summary, conv_text)
            
            st.rerun()

if "summary" in st.session_state:
    st.success("Summary generated – screenshot or download below:")
    st.markdown(st.session_state.summary)
    st.download_button(
        label="📥 Download Summary (.txt)",
        data=st.session_state.summary,
        file_name=f"anchorpoint_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain",
    )
    st.caption("This diagnostic is a field log entry and has been saved to your Registry Intelligence with a GAS score and leakage estimate.")
    if st.button("Start new conversation"):
        create_new_conversation()
        del st.session_state.summary
        del st.session_state.summary_shown
        st.rerun()
