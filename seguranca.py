import streamlit as st
import subprocess
import requests
from cryptography.fernet import Fernet
import os

# --- CONFIGURAÇÕES DO DONO (VOCÊ) ---
CHAVE_MESTRA = "EcdB-xzx7Rg599SmkImPSDItL34cUFlcCqgrbID849s="
URL_SERVIDOR = "https://meu-servidor-licenca.onrender.com" # Mude sempre que o ngrok reiniciar
fernet = Fernet(CHAVE_MESTRA)
ARQUIVO_LICENCA = "license.dat"

def get_hwid():
    """Captura o UUID da placa-mãe (Windows)."""
    try:
        cmd = 'wmic csproduct get uuid'
        uuid = subprocess.check_output(cmd, shell=True).decode().split('\n')[1].strip()
        return uuid
    except:
        return "HWID_ERRO"

def salvar_token_local(token):
    """Salva o token criptografado para uso offline."""
    with open(ARQUIVO_LICENCA, "w") as f:
        f.write(token)

def verificar_acesso_offline():
    """Tenta validar o HWID sem internet usando o token local."""
    if not os.path.exists(ARQUIVO_LICENCA):
        return False
    
    try:
        with open(ARQUIVO_LICENCA, "r") as f:
            token_criptografado = f.read()
        
        # Descriptografa o conteúdo: "usuario|hwid"
        dados = fernet.decrypt(token_criptografado.encode()).decode()
        user_token, hwid_token = dados.split("|")
        
        # O hardware atual é o mesmo que está no token?
        if hwid_token == get_hwid():
            return True
    except:
        return False
    return False

def interface_login():
    # Se tem o arquivo, vamos validar
    if os.path.exists(ARQUIVO_LICENCA):
        with open(ARQUIVO_LICENCA, "r") as f:
            token = f.read()
        
        # CHECAGEM DE BLOQUEIO REAL-TIME
        if not validar_status_servidor(token):
            os.remove(ARQUIVO_LICENCA) # Mata a licença local
            st.error("❌ Sua licença foi revogada pelo administrador.")
            st.stop()
        
        # Se passou no servidor ou está sem internet, verifica o HWID
        if verificar_acesso_offline():
            st.session_state.autenticado = True
        else:
            st.session_state.autenticado = False
    else:
        st.session_state.autenticado = False
        
    if not st.session_state.autenticado:
        st.title("🔒 Ativação de Licença")
        st.info("Entre com suas credenciais para ativar este computador.")
        
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        
        if st.button("Ativar Sistema"):
            # O 'spinner' avisa o usuário que o servidor está ligando
            with st.spinner("Conectando ao servidor de licenças... (Pode demorar 30s no primeiro acesso)"):
                try:
                    hwid_atual = get_hwid()
                    payload = {"user": usuario, "pass": senha, "hwid": hwid_atual}
                    
                    response = requests.post(f"{URL_SERVIDOR}/login", json=payload, timeout=40) # Aumentei o timeout
                    
                    if response.status_code == 200:
                        token = response.json().get("token")
                        salvar_token_local(token)
                        st.success("Licença Validada!")
                        st.session_state.autenticado = True
                        st.rerun()
                    else:
                        erro = response.json().get("detail")
                        st.error(f"Erro: {erro}")
                except Exception as e:
                    st.error("Servidor em standby. Tente novamente em alguns segundos.")
        
        st.stop()

def validar_status_servidor(token_criptografado):
    """Pergunta ao servidor se o token/usuário ainda é válido."""
    try:
        # Decifra apenas para pegar o nome do usuário
        dados = fernet.decrypt(token_criptografado.encode()).decode()
        username, hwid = dados.split("|")
        
        # Faz uma chamada rápida ao servidor
        response = requests.get(f"{URL_SERVIDOR}/admin/listar_usuarios", timeout=5)
        if response.status_code == 200:
            usuarios = response.json()
            for u in usuarios:
                if u['username'] == username:
                    return u['status_ativo'] # Retorna se está ativo ou não
    except:
        return True # Se a internet cair, permite o acesso offline (opcional)
    return True