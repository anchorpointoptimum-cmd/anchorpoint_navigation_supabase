import streamlit as st
import uuid
from datetime import datetime
from groq import Groq
from supabase import create_client, Client
import os

# ========== PAGE CONFIG ==========
st.set_page_config(page_title="Anchorpoint Navigator", page_icon="⚓", layout="wide")

st.title("⚓ Anchorpoint AI Navigator")
st.caption("Diagnosing operational gaps. Stewarding certainty.")

# ========== LOAD SECRETS ==========
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

# ========== INIT SUPABASE CLIENT ==========
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ========== GROQ CLIENT ==========
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
    st.session_state.conversations_list = []  # for authenticated users
if "messages" not in st.session_state:
    st.session_state.messages = []
if "edit_msg_id" not in st.session_state:
    st.session_state.edit_msg_id = None

# ========== HELPER FUNCTIONS ==========
def login_user(email, password):
    try:
        resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.auth_user = resp.user
        st.session_state.guest_mode = False
        load_user_conversations()
        return True
    except Exception as e:
        st.error(f"Login failed: {e}")
        return False

def signup_user(email, password):
    try:
        resp = supabase.auth.sign_up({"email": email, "password": password})
        st.session_state.auth_user = resp.user
        st.session_state.guest_mode = False
        # Profile is auto-created by SQL trigger
        load_user_conversations()
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
    st.rerun()

def load_user_conversations():
    if not st.session_state.auth_user:
        return
    user_id = st.session_state.auth_user.id
    resp = supabase.table("conversations").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
    st.session_state.conversations_list = resp.data
    if st.session_state.conversations_list and not st.session_state.current_conv_id:
        st.session_state.current_conv_id = st.session_state.conversations_list[0]["id"]
        load_conversation_messages(st.session_state.current_conv_id)

def load_conversation_messages(conv_id):
    resp = supabase.table("messages").select("*").eq("conversation_id", conv_id).order("created_at", asc=True).execute()
    # Convert to the format used in the chat (list of dicts with role, content)
    messages = [{"role": m["role"], "content": m["content"], "id": m["id"], "parent_id": m.get("parent_id")} for m in resp.data]
    # Ensure system message is first
    if not messages or messages[0]["role"] != "system":
        system_msg = {"role": "system", "content": system_content + "\n\nRemember: You are a Navigator. Lead with questions.", "id": str(uuid.uuid4())}
        messages.insert(0, system_msg)
    st.session_state.messages = messages
    st.session_state.current_conv_id = conv_id

def create_new_conversation():
    if st.session_state.auth_user:
        # Create in Supabase
        new_conv = {
            "user_id": st.session_state.auth_user.id,
            "title": "New conversation",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        resp = supabase.table("conversations").insert(new_conv).execute()
        conv_id = resp.data[0]["id"]
        # Add system message
        supabase.table("messages").insert({
            "conversation_id": conv_id,
            "role": "system",
            "content": system_content + "\n\nRemember: You are a Navigator. Lead with questions."
        }).execute()
        load_user_conversations()
        load_conversation_messages(conv_id)
    else:
        # Guest mode: simply reset messages
        st.session_state.messages = [{"role": "system", "content": system_content + "\n\nRemember: You are a Navigator. Lead with questions.", "id": str(uuid.uuid4())}]
        st.session_state.current_conv_id = None
    st.rerun()

def delete_conversation(conv_id):
    if st.session_state.auth_user:
        supabase.table("conversations").delete().eq("id", conv_id).execute()
        load_user_conversations()
        if st.session_state.current_conv_id == conv_id:
            if st.session_state.conversations_list:
                st.session_state.current_conv_id = st.session_state.conversations_list[0]["id"]
                load_conversation_messages(st.session_state.current_conv_id)
            else:
                create_new_conversation()
        st.rerun()

def switch_conversation(conv_id):
    load_conversation_messages(conv_id)
    st.rerun()

def update_conversation_title(conv_id, title):
    if st.session_state.auth_user:
        supabase.table("conversations").update({"title": title, "updated_at": datetime.now().isoformat()}).eq("id", conv_id).execute()
        load_user_conversations()

def save_message_to_db(conv_id, role, content, parent_id=None):
    if st.session_state.auth_user:
        supabase.table("messages").insert({
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "parent_id": parent_id
        }).execute()

def save_conversation_messages(conv_id, messages_list):
    if st.session_state.auth_user:
        # Delete all existing messages for this conversation and reinsert (simpler)
        supabase.table("messages").delete().eq("conversation_id", conv_id).execute()
        for msg in messages_list:
            if msg["role"] == "system":
                continue  # system message is handled separately at creation
            supabase.table("messages").insert({
                "conversation_id": conv_id,
                "role": msg["role"],
                "content": msg["content"],
                "parent_id": msg.get("parent_id")
            }).execute()
        # Update conversation updated_at
        supabase.table("conversations").update({"updated_at": datetime.now().isoformat()}).eq("id", conv_id).execute()

def get_assistant_response(messages_list):
    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages_list if m["role"] != "system"]
    system_msg = next((m for m in messages_list if m["role"] == "system"), None)
    full_messages = []
    if system_msg:
        full_messages.append({"role": "system", "content": system_msg["content"]})
    full_messages.extend(api_messages)
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=full_messages,
        temperature=0.7,
        max_tokens=500
    )
    return response.choices[0].message.content

# ========== SIDEBAR: AUTH & HISTORY ==========
with st.sidebar:
    if st.session_state.auth_user:
        st.write(f"👤 {st.session_state.auth_user.email}")
        if st.button("Logout"):
            logout_user()
    else:
        st.markdown("### 🔐 Account")
        tab1, tab2 = st.tabs(["Login", "Sign up"])
        with tab1:
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_password")
            if st.button("Login", key="login_btn"):
                if login_email and login_password:
                    login_user(login_email, login_password)
                else:
                    st.warning("Enter email and password")
        with tab2:
            signup_email = st.text_input("Email", key="signup_email")
            signup_password = st.text_input("Password", type="password", key="signup_password")
            if st.button("Sign up", key="signup_btn"):
                if signup_email and signup_password:
                    signup_user(signup_email, signup_password)
                else:
                    st.warning("Enter email and password")

    st.divider()
    st.markdown("### 📜 History")
    if st.button("➕ New conversation", use_container_width=True):
        create_new_conversation()

    if st.session_state.auth_user:
        for conv in st.session_state.conversations_list:
            display_title = conv["title"][:35] + ("..." if len(conv["title"]) > 35 else "")
            col1, col2 = st.columns([0.85, 0.15])
            with col1:
                if st.button(display_title, key=f"conv_{conv['id']}", use_container_width=True):
                    switch_conversation(conv["id"])
            with col2:
                if st.button("🗑️", key=f"del_{conv['id']}"):
                    delete_conversation(conv["id"])
            st.caption(conv.get("updated_at", conv["created_at"])[:10])
    else:
        st.info("💡 Sign in to save conversations and access history across devices.")
        # Show a simple "current session" note for guest
        if st.session_state.messages:
            st.caption("Guest session (not saved)")

# ========== MAIN CHAT AREA ==========
if st.session_state.messages:
    # Display messages (skip system message)
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
    # First time: create a new conversation or show intro
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
                # Update the message content
                msg_to_edit["content"] = new_content
                # Delete all messages after this one
                idx = st.session_state.messages.index(msg_to_edit)
                st.session_state.messages = st.session_state.messages[:idx+1]
                # Regenerate assistant response
                new_reply = get_assistant_response(st.session_state.messages)
                assistant_msg = {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": new_reply,
                    "parent_id": msg_to_edit["id"]
                }
                st.session_state.messages.append(assistant_msg)
                # Save to DB if authenticated
                if st.session_state.auth_user and st.session_state.current_conv_id:
                    save_conversation_messages(st.session_state.current_conv_id, st.session_state.messages)
                # Update conversation title if it's the first user message
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
        # Add user message
        user_msg = {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": prompt
        }
        st.session_state.messages.append(user_msg)
        # Get assistant response
        with st.spinner("Diagnosing..."):
            reply = get_assistant_response(st.session_state.messages)
        assistant_msg = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": reply,
            "parent_id": user_msg["id"]
        }
        st.session_state.messages.append(assistant_msg)

        # Save to DB if authenticated
        if st.session_state.auth_user:
            if not st.session_state.current_conv_id:
                # This should not happen; but create a new conversation just in case
                create_new_conversation()
            else:
                save_conversation_messages(st.session_state.current_conv_id, st.session_state.messages)
                # Update conversation title (if first user message)
                user_msgs = [m for m in st.session_state.messages if m["role"] == "user"]
                if len(user_msgs) == 1:
                    title = user_msgs[0]["content"][:40] + ("..." if len(user_msgs[0]["content"]) > 40 else "")
                    update_conversation_title(st.session_state.current_conv_id, title)
                # Refresh conversation list to show updated title/timestamp
                load_user_conversations()
        else:
            # Guest mode: no persistence, but show a banner reminder
            if len([m for m in st.session_state.messages if m["role"] == "user"]) == 1:
                st.info("💡 You're in guest mode. [Sign up](#) to save this conversation and access it later.")

        st.rerun()

# ========== SUMMARY GENERATION ==========
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
            st.rerun()

if "summary" in st.session_state:
    st.success("Summary generated – screenshot or copy below:")
    st.markdown(st.session_state.summary)
    st.caption("📸 Screenshot this to share with your team.")
    if st.button("Start new conversation"):
        create_new_conversation()
        # Clear summary flag
        del st.session_state.summary
        del st.session_state.summary_shown
        st.rerun()