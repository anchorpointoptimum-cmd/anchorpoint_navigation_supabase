import streamlit as st
import hashlib
import uuid
from datetime import datetime
from groq import Groq
from supabase import create_client, Client
import os
import json
import pandas as pd
from fpdf import FPDF
import tempfile

# ========== PASSWORD PROTECTION ==========
def check_password():
    """Returns True if the user enters the correct password."""
    def password_entered():
        if hashlib.sha256(st.session_state["password"].encode()).hexdigest() == st.secrets["password_hash"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter password", type="password", on_change=password_entered, key="password")
        st.stop()
    elif not st.session_state["password_correct"]:
        st.text_input("Enter password", type="password", on_change=password_entered, key="password")
        st.error("Incorrect password")
        st.stop()
    else:
        return True

check_password()

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
    /* Fix text area background and placeholder visibility */
    .stTextArea textarea {
        background-color: #ffffff !important;
        color: #111111 !important;
        border: 1px solid #cccccc;
    }
    .stTextArea textarea::placeholder {
        color: #6c757d !important;  /* visible gray */
        opacity: 1;
    }
    /* Ensure the text input itself is readable */
    .stTextInput input {
        background-color: #ffffff !important;
        color: #111111 !important;
    }
</style>
""", unsafe_allow_html=True)
# ========== MAIN HEADER WITH LOGO ==========
logo_url = "https://raw.githubusercontent.com/anchorpointoptimum-cmd/anchorpoint_navigation_supabase/main/anchorpoint_official_logo.v2.jpeg"
st.image(logo_url, width=150)
st.title("Anchorpoint AI Navigator")
st.caption("Diagnosing operational gaps. Stewarding certainty.")

# ========== LOAD SECRETS ==========
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
APP_URL = st.secrets.get("APP_URL", "https://anchorpointnavigationsupabase-lq5rflwrxgztuq8awnpqx5.streamlit.app")
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
if "current_org_id" not in st.session_state:
    st.session_state.current_org_id = None
if "user_orgs" not in st.session_state:
    st.session_state.user_orgs = []
if "org_role" not in st.session_state:
    st.session_state.org_role = None
if "pending_context" not in st.session_state:
    st.session_state.pending_context = None
if "context_shown_for" not in st.session_state:
    st.session_state.context_shown_for = None

# ========== RESTORE SESSION FROM COOKIE ==========
if not st.session_state.auth_user:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.auth_user = session.user
            st.session_state.guest_mode = False
            ensure_profile_exists()
            load_user_organizations()
            if st.session_state.user_orgs and not st.session_state.current_org_id:
                st.session_state.current_org_id = st.session_state.user_orgs[0]["id"]
                st.session_state.org_role = st.session_state.user_orgs[0]["role"]
                load_user_conversations()
                if st.session_state.current_conv_id is None:
                    create_new_conversation()
            st.rerun()
    except Exception:
        pass

# ========== INVITE HANDLER ==========
query_params = st.query_params
accept_token = query_params.get("accept_invite")
if accept_token:
    if st.session_state.auth_user:
        try:
            resp = supabase.table("invites").select("*").eq("token", accept_token).eq("used_at", None).gt("expires_at", datetime.now().isoformat()).execute()
            if not resp.data:
                st.error("Invalid or expired invite link.")
            else:
                invite = resp.data[0]
                supabase.table("organization_members").insert({
                    "organization_id": invite["organization_id"],
                    "user_id": st.session_state.auth_user.id,
                    "role": invite["role"]
                }).execute()
                supabase.table("invites").update({"used_at": datetime.now().isoformat()}).eq("token", accept_token).execute()
                st.success("You have been added to the organization. Refreshing...")
                st.query_params.clear()
                st.rerun()
        except Exception as e:
            st.error(f"Could not accept invite: {e}")
    else:
        st.warning("Please log in to accept the invitation.")
        st.stop()

# ========== HELPER FUNCTIONS ==========
def friendly_error(user_message: str):
    st.error(f"⚠️ {user_message}")

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

def load_user_organizations():
    if not st.session_state.auth_user:
        return
    try:
        resp = supabase.table("organization_members").select("organization_id, role, organizations(*)").eq("user_id", st.session_state.auth_user.id).execute()
        orgs = []
        for item in resp.data:
            orgs.append({
                "id": item["organization_id"],
                "name": item["organizations"]["name"],
                "slug": item["organizations"]["slug"],
                "role": item["role"]
            })
        st.session_state.user_orgs = orgs
        if orgs and not st.session_state.current_org_id:
            st.session_state.current_org_id = orgs[0]["id"]
            st.session_state.org_role = orgs[0]["role"]
    except Exception:
        st.session_state.user_orgs = []

def load_user_conversations():
    if not st.session_state.auth_user or not st.session_state.current_org_id:
        return
    try:
        resp = supabase.table("conversations").select("*").eq("user_id", st.session_state.auth_user.id).eq("organization_id", st.session_state.current_org_id).order("updated_at", desc=True).execute()
        st.session_state.conversations_list = resp.data
        if st.session_state.conversations_list and not st.session_state.current_conv_id:
            st.session_state.current_conv_id = st.session_state.conversations_list[0]["id"]
            load_conversation_messages(st.session_state.current_conv_id)
        elif not st.session_state.conversations_list:
            create_new_conversation()
    except Exception as e:
        st.error(f"Error loading conversations: {e}")
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
    except Exception as e:
        st.error(f"Unable to load conversation: {e}")

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

    if st.session_state.auth_user and st.session_state.current_org_id:
        try:
            new_conv = {
                "user_id": st.session_state.auth_user.id,
                "organization_id": st.session_state.current_org_id,
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
        except Exception as e:
            st.error(f"Unable to start a new conversation: {e}")
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
            st.error("Could not delete conversation. It may have been already removed.")
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
            st.error("Could not update title.")

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
            st.error("Your conversation may not have been saved. You can still continue, but progress might be lost on refresh.")

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
    if not st.session_state.auth_user or not st.session_state.current_org_id:
        return False
    
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
        
        supabase.table("registry_entries").insert({
            "conversation_id": conv_id,
            "organization_id": st.session_state.current_org_id,
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

def login_user(email, password):
    try:
        resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.auth_user = resp.user
        st.session_state.guest_mode = False
        ensure_profile_exists()
        load_user_organizations()
        if st.session_state.user_orgs:
            st.session_state.current_org_id = st.session_state.user_orgs[0]["id"]
            st.session_state.org_role = st.session_state.user_orgs[0]["role"]
            load_user_conversations()
            if st.session_state.current_conv_id is None:
                create_new_conversation()
        st.rerun()
        return True
    except Exception as e:
        st.error(f"Login failed: {e}")
        return False

def signup_user(email, password):
    try:
        resp = supabase.auth.sign_up({"email": email, "password": password})
        st.session_state.auth_user = resp.user
        st.session_state.guest_mode = False
        ensure_profile_exists()
        load_user_organizations()
        st.rerun()
        return True
    except Exception as e:
        st.error(f"Signup failed: {e}")
        return False

def logout_user():
    supabase.auth.sign_out()
    st.session_state.auth_user = None
    st.session_state.guest_mode = True
    st.session_state.current_conv_id = None
    st.session_state.messages = []
    st.session_state.show_observatory = False
    st.session_state.current_org_id = None
    st.session_state.user_orgs = []
    st.session_state.org_role = None
    st.session_state.pending_context = None
    st.session_state.context_shown_for = None
    st.rerun()

def switch_organization(org_id):
    st.session_state.current_org_id = org_id
    for org in st.session_state.user_orgs:
        if org["id"] == org_id:
            st.session_state.org_role = org["role"]
            break
    st.session_state.current_conv_id = None
    st.session_state.messages = []
    st.session_state.pending_context = None
    st.session_state.context_shown_for = None
    load_user_conversations()
    st.rerun()

def create_invite(org_id, email, role):
    token = hashlib.sha256(f"{org_id}{email}{uuid.uuid4()}".encode()).hexdigest()[:32]
    supabase.table("invites").insert({
        "organization_id": org_id,
        "email": email,
        "role": role,
        "token": token
    }).execute()
    return f"{APP_URL}?accept_invite={token}"

def create_organization(name, slug):
    if not st.session_state.auth_user:
        return False
    try:
        resp = supabase.table("organizations").insert({
            "name": name,
            "slug": slug,
            "created_by": st.session_state.auth_user.id
        }).execute()
        org_id = resp.data[0]["id"]
        supabase.table("organization_members").insert({
            "organization_id": org_id,
            "user_id": st.session_state.auth_user.id,
            "role": "admin"
        }).execute()
        load_user_organizations()
        st.session_state.current_org_id = org_id
        st.session_state.org_role = "admin"
        load_user_conversations()
        return True
    except Exception as e:
        st.error(f"Could not create organization: {e}")
        return False

def show_observatory():
    st.subheader("🔭 Operational Intelligence Observatory")
    st.caption(f"Aggregated insights for current organization")
    if st.session_state.org_role not in ['admin', 'member']:
        st.warning("You do not have permission to view the Observatory for this organization.")
        if st.button("← Back to Navigator"):
            st.session_state.show_observatory = False
            st.rerun()
        return
    
    try:
        entries = supabase.table("registry_entries").select("*").eq("organization_id", st.session_state.current_org_id).execute()
        df = pd.DataFrame(entries.data)
        
        if not df.empty:
            st.subheader("Gap Type Distribution")
            gap_counts = df['gap_type'].value_counts().reset_index()
            gap_counts.columns = ['Gap Type', 'Count']
            st.bar_chart(gap_counts.set_index('Gap Type'))
            
            st.subheader("Top Persistence Drivers")
            driver_counts = df['persistence_driver'].value_counts().head(5).reset_index()
            driver_counts.columns = ['Driver', 'Count']
            st.dataframe(driver_counts)
            
            st.subheader("Most Referenced Assets")
            asset_counts = df['linked_asset'].value_counts().head(5).reset_index()
            asset_counts.columns = ['Asset', 'Count']
            st.dataframe(asset_counts)
            
            st.subheader("Entries Over Time")
            df['date'] = pd.to_datetime(df['created_at']).dt.date
            timeline = df.groupby('date').size().reset_index(name='count')
            st.line_chart(timeline.set_index('date'))
            
            st.subheader("GAS Score Distribution")
            gas_data = df[df['gas_score'].notna()]
            if not gas_data.empty:
                avg_gas = gas_data['gas_score'].mean()
                st.metric("Average GAS Score", f"{avg_gas:.1f}")
                gas_data['decile'] = (gas_data['gas_score'] // 10) * 10
                decile_counts = gas_data['decile'].value_counts().sort_index().reset_index()
                decile_counts.columns = ['GAS Score Range', 'Count']
                st.bar_chart(decile_counts.set_index('GAS Score Range'))
            
            st.subheader("Estimated Off‑platform Leakage")
            leak_data = df[df['leakage_estimate'].notna()]
            if not leak_data.empty:
                avg_leak = leak_data['leakage_estimate'].mean()
                st.metric("Average Leakage", f"{avg_leak:.1f}%")
                leak_data['leak_bucket'] = (leak_data['leakage_estimate'] // 10) * 10
                leak_counts = leak_data['leak_bucket'].value_counts().sort_index().reset_index()
                leak_counts.columns = ['Leakage % Range', 'Count']
                st.bar_chart(leak_counts.set_index('Leakage % Range'))
            
            if st.checkbox("Show raw data"):
                st.dataframe(df)
        else:
            st.info("No registry entries yet. Generate summaries to see intelligence.")
    except Exception as e:
        st.error(f"Could not load observatory data: {e}")
    
    if st.button("← Back to Navigator"):
        st.session_state.show_observatory = False
        st.rerun()

# ========== SHARED CONVERSATION VIEW ==========
share_token = query_params.get("share")
if share_token and not accept_token:
    conv_resp = supabase.table("conversations").select("id, organization_id").eq("share_token", share_token).execute()
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
    st.image(logo_url, use_container_width=True)
    st.markdown("---")

    if st.session_state.auth_user:
        st.write(f"👤 {st.session_state.auth_user.email}")
        
        if st.session_state.user_orgs:
            org_names = {org["id"]: f"{org['name']} ({org['role']})" for org in st.session_state.user_orgs}
            selected_org_id = st.selectbox(
                "Organization",
                options=list(org_names.keys()),
                format_func=lambda x: org_names[x],
                index=0 if st.session_state.current_org_id else 0,
                key="org_selector"
            )
            if selected_org_id != st.session_state.current_org_id:
                switch_organization(selected_org_id)
        else:
            st.info("You are not a member of any organization.")
        
        with st.expander("➕ Create new organization"):
            org_name = st.text_input("Organization name")
            org_slug = st.text_input("Slug (unique identifier, no spaces)")
            if st.button("Create Organization"):
                if org_name and org_slug:
                    create_organization(org_name, org_slug)
                else:
                    st.error("Please enter both name and slug.")
        
        if st.session_state.org_role == 'admin' and st.session_state.current_org_id:
            with st.expander("👥 Invite member"):
                invite_email = st.text_input("Email address")
                invite_role = st.selectbox("Role", ["member", "observer"])
                if st.button("Generate invite link"):
                    if invite_email:
                        link = create_invite(st.session_state.current_org_id, invite_email, invite_role)
                        st.success(f"Invite link (send to {invite_email}):")
                        st.code(link, language="text")
                    else:
                        st.error("Please enter an email.")
        
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
                    st.error("Please enter both email and password.")
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
                    st.error("Please enter an email and a password (at least 6 characters).")

    st.divider()
    st.markdown("### 📜 Intelligence Log")
    if st.button("➕ New conversation", use_container_width=True):
        create_new_conversation()

    if st.session_state.auth_user and st.session_state.current_org_id:
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
                            st.error("Title cannot be empty.")
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
        
        if st.session_state.org_role in ['admin', 'member']:
            st.divider()
            st.markdown("### 🔭 Observatory")
            if st.button("📊 View Intelligence Dashboard"):
                st.session_state.show_observatory = True
                st.rerun()
    elif st.session_state.auth_user and not st.session_state.current_org_id:
        st.info("Create or join an organization to start saving conversations.")
    else:
        st.info("💡 Sign in to save conversations and contribute to your governance profile.")
        if st.session_state.messages:
            st.caption("Guest session (intelligence not persisted)")

# ========== MAIN CHAT AREA (with context capture) ==========
if st.session_state.messages:
    for idx, msg in enumerate(st.session_state.messages):
        if msg["role"] == "system":
            continue
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "user":
                if st.button("✏️", key=f"edit_{msg['id']}"):
                    st.session_state.edit_msg_id = msg["id"]
                    st.rerun()
            # After assistant message that ends with "?" and not already answered, show context field
            if msg["role"] == "assistant" and msg["content"].strip().endswith("?"):
                if idx == len(st.session_state.messages) - 1 and st.session_state.context_shown_for != msg["id"]:
                    with st.form(key=f"context_form_{msg['id']}"):
                        context = st.text_area(
                            "Optional: Add context to help me understand better (e.g., 'The manager is often away on Mondays')",
                            key=f"context_{msg['id']}",
                            placeholder="e.g., The store manager is often away on Mondays, so the team uses WhatsApp."
                        )
                        submitted = st.form_submit_button("Submit context & continue")
                        if submitted:
                            if context.strip():
                                st.session_state.pending_context = context.strip()
                            st.session_state.context_shown_for = msg["id"]
                            st.rerun()
else:
    if not st.session_state.messages:
        create_new_conversation()
        st.rerun()

# ========== EDIT MODAL ==========
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

# ========== CHAT INPUT (with context injection) ==========
if not st.session_state.edit_msg_id:
    if prompt := st.chat_input("Describe an operational process or challenge..."):
        # Inject pending context if any
        if st.session_state.pending_context:
            full_prompt = f"[Context provided: {st.session_state.pending_context}]\n\nUser: {prompt}"
            st.session_state.pending_context = None
        else:
            full_prompt = prompt
        
        user_msg = {"id": str(uuid.uuid4()), "role": "user", "content": full_prompt}
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

# ========== SUMMARY GENERATION (PDF + text) ==========
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
            
            if st.session_state.auth_user and st.session_state.current_conv_id:
                save_registry_entry(st.session_state.current_conv_id, summary, conv_text)
            
            st.rerun()

if "summary" in st.session_state:
    st.success("Summary generated – download below:")
    st.markdown(st.session_state.summary)

    # Text download
    st.download_button(
        label="📥 Download Summary (.txt)",
        data=st.session_state.summary,
        file_name=f"anchorpoint_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain",
    )

    # PDF download
    try:
        class PDF(FPDF):
            def header(self):
                self.set_font('Arial', 'B', 12)
                self.cell(0, 10, 'Anchorpoint AI Navigator', 0, 1, 'C')
                self.ln(5)

            def footer(self):
                self.set_y(-15)
                self.set_font('Arial', 'I', 8)
                self.cell(0, 10, f'Generated on {datetime.now().strftime("%Y-%m-%d %H:%M")} - Anchorpoint Operational Intelligence', 0, 0, 'C')

        pdf = PDF()
        pdf.add_page()
        pdf.set_font('Arial', '', 11)
        summary_text_plain = st.session_state.summary.replace('**', '').replace('__', '')
        pdf.multi_cell(0, 8, summary_text_plain)
        pdf.ln(5)
        pdf.cell(0, 8, "This diagnostic is a field log entry and can inform your Governance Adoption Score (GAS).", 0, 1, 'C')

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf.output(tmp.name)
            tmp.seek(0)
            pdf_data = tmp.read()

        st.download_button(
            label="📄 Download Summary (PDF)",
            data=pdf_data,
            file_name=f"anchorpoint_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.warning(f"PDF export not available: {e}")

    st.caption("This diagnostic is a field log entry and has been saved to your Registry Intelligence with a GAS score and leakage estimate.")
    if st.button("Start new conversation"):
        create_new_conversation()
        del st.session_state.summary
        del st.session_state.summary_shown
        st.rerun()
