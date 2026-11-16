import pygame
import random
import os
import cv2
import json
import librosa
import numpy as np
import hashlib
import urllib.request
import urllib.error
from moviepy import VideoFileClip

# ============================================================
# NEON BEAT
# ============================================================

pygame.init()
pygame.mixer.init()

LARGURA, ALTURA = 1000, 750
tela = pygame.display.set_mode((LARGURA, ALTURA), pygame.RESIZABLE)
pygame.display.set_caption("Neon Beat")
relogio = pygame.time.Clock()

# ============================================================
# CONFIGURAÇÕES
# ============================================================

COR_FUNDO = (18, 18, 28)
COR_AZUL = (50, 200, 255)
COR_VERDE = (50, 255, 100)
COR_AMARELO = (255, 220, 50)
COR_VERMELHO = (255, 60, 60)
COR_TEXTO = (240, 240, 250)
COR_SECUNDARIA = (150, 150, 170)

CORES = [
    (255, 50, 100),
    (50, 200, 255),
    (50, 255, 100),
    (255, 200, 50)
]

API_BASE_URL = ""

ARQUIVO_CONFIG = "configuracoes.json"
ARQUIVO_RECORDE = "recordes.json"
ARQUIVO_CACHE = "cache_audio"
PASTA_MUSICAS = "musicas"

os.makedirs(PASTA_MUSICAS, exist_ok=True)
os.makedirs(ARQUIVO_CACHE, exist_ok=True)

RAIO_NOTA = 46

fonte_titulo = pygame.font.SysFont("Arial", 48, bold=True)
fonte_menu = pygame.font.SysFont("Arial", 23)
fonte_hud = pygame.font.SysFont("Arial", 27, bold=True)
fonte_feedback = pygame.font.SysFont("Arial", 32, bold=True)
fonte_teclas = pygame.font.SysFont("Arial", 30, bold=True)
fonte_pequena = pygame.font.SysFont("Arial", 17)

# ============================================================
# CONFIGURAÇÕES DO JOGADOR
# ============================================================

def carregar_configuracoes():
    padrao = {
        "teclas": [
            pygame.K_a,
            pygame.K_s,
            pygame.K_k,
            pygame.K_l
        ],
        "usuario": "",
        "token": ""
    }

    if os.path.exists(ARQUIVO_CONFIG):
        try:
            with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)

            padrao.update(dados)

            teclas = padrao.get("teclas", [])

            if len(teclas) != 4 or len(set(teclas)) != 4:
                padrao["teclas"] = [
                    pygame.K_a,
                    pygame.K_s,
                    pygame.K_k,
                    pygame.K_l
                ]

        except (json.JSONDecodeError, OSError, TypeError):
            pass

    return padrao


config = carregar_configuracoes()
TECLAS = config["teclas"]


def salvar_configuracoes():
    config["teclas"] = TECLAS

    with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as arquivo:
        json.dump(config, arquivo, indent=4, ensure_ascii=False)


def nome_tecla(tecla):
    try:
        return pygame.key.name(tecla).upper()
    except Exception:
        return "?"


# ============================================================
# RECORDES LOCAIS
# ============================================================

def carregar_recordes():
    if os.path.exists(ARQUIVO_RECORDE):
        try:
            with open(ARQUIVO_RECORDE, "r", encoding="utf-8") as arquivo:
                return json.load(arquivo)
        except (json.JSONDecodeError, OSError):
            return {}

    return {}


def salvar_recordes(recordes):
    with open(ARQUIVO_RECORDE, "w", encoding="utf-8") as arquivo:
        json.dump(recordes, arquivo, indent=4, ensure_ascii=False)


recordes = carregar_recordes()

# ============================================================
# COMUNICAÇÃO COM A API
# ============================================================

def requisicao_api(endpoint, metodo="GET", dados=None):
    if not API_BASE_URL:
        return None, "Servidor não configurado."

    url = API_BASE_URL.rstrip("/") + endpoint

    cabecalhos = {
        "Content-Type": "application/json"
    }

    token = config.get("token", "")

    if token:
        cabecalhos["Authorization"] = "Bearer " + token

    corpo = None

    if dados is not None:
        corpo = json.dumps(dados).encode("utf-8")

    requisicao = urllib.request.Request(
        url,
        data=corpo,
        headers=cabecalhos,
        method=metodo
    )

    try:
        with urllib.request.urlopen(requisicao, timeout=8) as resposta:
            conteudo = resposta.read().decode("utf-8")

            if conteudo:
                return json.loads(conteudo), None

            return {}, None

    except urllib.error.HTTPError as erro:
        try:
            mensagem = erro.read().decode("utf-8")
            dados_erro = json.loads(mensagem)
            mensagem = dados_erro.get("message", mensagem)
        except Exception:
            mensagem = str(erro)

        return None, mensagem

    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "Não foi possível conectar ao servidor."

    except json.JSONDecodeError:
        return None, "O servidor enviou uma resposta inválida."


def registrar_usuario(usuario, senha):
    return requisicao_api(
        "/auth/register",
        "POST",
        {
            "username": usuario,
            "password": senha
        }
    )


def fazer_login(usuario, senha):
    return requisicao_api(
        "/auth/login",
        "POST",
        {
            "username": usuario,
            "password": senha
        }
    )


def enviar_pontuacao(fingerprint, nome_musica, pontuacao, bpm, duracao):
    if not config.get("token"):
        return None, "Faça login para enviar sua pontuação."

    return requisicao_api(
        "/ranking/submit",
        "POST",
        {
            "fingerprint": fingerprint,
            "song_name": nome_musica,
            "score": int(pontuacao),
            "bpm": float(bpm),
            "duration": float(duracao)
        }
    )


def buscar_ranking(fingerprint):
    return requisicao_api(
        "/ranking/" + fingerprint,
        "GET"
    )


# ============================================================
# MÚSICAS
# ============================================================

def listar_musicas():
    return sorted([
        f for f in os.listdir(PASTA_MUSICAS)
        if f.lower().endswith((".mp3", ".mp4"))
    ])


tela_cheia = False


def alternar_tela_cheia():
    global tela, LARGURA, ALTURA, tela_cheia

    tela_cheia = not tela_cheia

    if tela_cheia:
        tela = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        tela = pygame.display.set_mode((1000, 750), pygame.RESIZABLE)

    LARGURA, ALTURA = tela.get_size()


# ============================================================
# IDENTIFICAÇÃO DA MÚSICA
# ============================================================

def criar_fingerprint(bpm, duracao, tempos_notas):
    duracao_quantizada = round(duracao / 2) * 2
    bpm_quantizado = round(bpm / 2) * 2

    intervalos = []

    for i in range(1, len(tempos_notas)):
        intervalo = tempos_notas[i] - tempos_notas[i - 1]
        intervalo = round(intervalo / 0.12) * 0.12
        intervalos.append(round(intervalo, 2))

    quantidade = 120

    if len(intervalos) > quantidade:
        passo = len(intervalos) / quantidade

        intervalos = [
            intervalos[int(i * passo)]
            for i in range(quantidade)
        ]

    assinatura = {
        "bpm": bpm_quantizado,
        "duracao": duracao_quantizada,
        "intervalos": intervalos
    }

    texto = json.dumps(
        assinatura,
        sort_keys=True,
        separators=(",", ":")
    )

    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ============================================================
# MAPA DE NOTAS
# ============================================================

def mapear_musica(caminho_audio, nome_base):
    arquivo_json = os.path.join(
        ARQUIVO_CACHE,
        nome_base + "_beatmap_v8.json"
    )

    if os.path.exists(arquivo_json):
        try:
            with open(arquivo_json, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)

            for item in dados["notas"]:
                item["spawnada"] = False

            tempos = [
                item["tempo_alvo"]
                for item in dados["notas"]
            ]

            fingerprint = criar_fingerprint(
                dados["bpm"],
                dados["duracao"],
                tempos
            )

            return (
                dados["notas"],
                dados["bpm"],
                dados["duracao"],
                fingerprint
            )

        except Exception:
            pass

    y, sr = librosa.load(
        caminho_audio,
        sr=22050,
        mono=True
    )

    duracao = float(librosa.get_duration(y=y, sr=sr))

    tempo, beat_frames = librosa.beat.beat_track(
        y=y,
        sr=sr
    )

    tempo_array = np.asarray(tempo).reshape(-1)

    bpm = (
        float(tempo_array[0])
        if tempo_array.size
        else 120.0
    )

    bpm = max(40.0, min(bpm, 300.0))

    onsets_frames = librosa.onset.onset_detect(
        y=y,
        sr=sr,
        wait=6,
        pre_avg=4,
        post_avg=4
    )

    tempos_onsets = librosa.frames_to_time(
        onsets_frames,
        sr=sr
    )

    tempos_batidas = librosa.frames_to_time(
        beat_frames,
        sr=sr
    )

    tempos_grade = []

    for batida in tempos_batidas:
        tempos_grade.append(float(batida))

    for i in range(len(tempos_batidas) - 1):
        inicio = float(tempos_batidas[i])
        fim = float(tempos_batidas[i + 1])

        if fim > inicio:
            tempos_grade.append((inicio + fim) / 2)

    candidatos = sorted(
        float(t)
        for t in list(tempos_onsets) + tempos_grade
        if float(t) >= 1.5
    )

    tempos_notas = []
    intervalo_minimo = 0.11

    for instante in candidatos:
        if (
            not tempos_notas
            or instante - tempos_notas[-1] >= intervalo_minimo
        ):
            tempos_notas.append(instante)

    mapa_notas = []
    fila_colunas = []
    ultima_coluna = None

    for tempo_seg in tempos_notas:

        if not fila_colunas:
            fila_colunas = [0, 1, 2, 3]
            random.shuffle(fila_colunas)

            if (
                len(fila_colunas) > 1
                and fila_colunas[0] == ultima_coluna
            ):
                fila_colunas[0], fila_colunas[1] = (
                    fila_colunas[1],
                    fila_colunas[0]
                )

        coluna = fila_colunas.pop(0)
        ultima_coluna = coluna

        mapa_notas.append({
            "tempo_alvo": float(tempo_seg),
            "col": coluna,
            "spawnada": False
        })

    fingerprint = criar_fingerprint(
        bpm,
        duracao,
        tempos_notas
    )

    with open(arquivo_json, "w", encoding="utf-8") as arquivo:
        json.dump({
            "bpm": bpm,
            "duracao": duracao,
            "notas": mapa_notas
        }, arquivo)

    return mapa_notas, bpm, duracao, fingerprint


# ============================================================
# LAYOUT
# ============================================================

def obter_layout():
    centro_x = LARGURA // 2
    espacamento = 120

    colunas_x = [
        centro_x - int(espacamento * 1.5),
        centro_x - int(espacamento * 0.5),
        centro_x + int(espacamento * 0.5),
        centro_x + int(espacamento * 1.5)
    ]

    y_alvo = ALTURA - 100

    return colunas_x, y_alvo


def desenhar_texto(texto, fonte, cor, x, y, centralizado=True):
    superficie = fonte.render(str(texto), True, cor)

    if centralizado:
        x -= superficie.get_width() // 2

    tela.blit(superficie, (x, y))


# ============================================================
# ESTADO DO JOGO
# ============================================================

estado = "MODO_MENU"

indice_menu = 0
rolagem_musicas = 0

cap = None
tem_video = False
fps_video = 30
frame_atual_video = 0
ultimo_frame_surface = None

notas = []
mapa_notas = []

bpm_atual = 120.0
duracao_atual = 0
fingerprint_atual = ""

pontos = 0
combo = 0
erros = 0
vida = 100

musica_atual = ""
jogo_iniciado = False

feedback_texto = ""
feedback_cor = COR_TEXTO
feedback_timer = 0

mensagem = ""
mensagem_cor = COR_TEXTO

usuario_digitado = ""
senha_digitada = ""
campo_ativo = "usuario"

indice_tecla_config = 0

dados_ranking = []


# ============================================================
# PARTIDA
# ============================================================

def iniciar_partida(nome_arquivo):
    global estado
    global cap, tem_video, fps_video
    global frame_atual_video, ultimo_frame_surface
    global notas, mapa_notas, bpm_atual
    global duracao_atual, fingerprint_atual
    global pontos, combo, erros, vida
    global jogo_iniciado, feedback_texto
    global musica_atual, feedback_timer

    caminho_completo = os.path.join(
        PASTA_MUSICAS,
        nome_arquivo
    )

    musica_atual = nome_arquivo

    notas = []
    pontos = 0
    combo = 0
    erros = 0
    vida = 100

    feedback_texto = ""
    feedback_timer = 0

    jogo_iniciado = False
    tem_video = False
    frame_atual_video = 0
    ultimo_frame_surface = None

    if cap is not None:
        cap.release()
        cap = None

    if nome_arquivo.lower().endswith(".mp4"):
        tem_video = True

        arquivo_audio = os.path.join(
            ARQUIVO_CACHE,
            nome_arquivo + ".mp3"
        )

        if not os.path.exists(arquivo_audio):
            clip = VideoFileClip(caminho_completo)

            if clip.audio is None:
                clip.close()
                raise ValueError("Este vídeo não possui áudio.")

            clip.audio.write_audiofile(
                arquivo_audio,
                logger=None
            )

            clip.close()

        cap = cv2.VideoCapture(caminho_completo)

        fps_video = cap.get(cv2.CAP_PROP_FPS) or 30

    else:
        arquivo_audio = caminho_completo

    (
        mapa_notas,
        bpm_atual,
        duracao_atual,
        fingerprint_atual
    ) = mapear_musica(
        arquivo_audio,
        nome_arquivo
    )

    pygame.mixer.music.load(arquivo_audio)
    pygame.mixer.music.play()

    jogo_iniciado = True
    estado = "JOGANDO"


# ============================================================
# SALVAR PONTUAÇÃO
# ============================================================

def finalizar_partida():
    global estado, jogo_iniciado, mensagem, mensagem_cor

    recorde_anterior = recordes.get(
        fingerprint_atual,
        0
    )

    if pontos > recorde_anterior:
        recordes[fingerprint_atual] = pontos
        salvar_recordes(recordes)

    if config.get("token"):
        resposta, erro = enviar_pontuacao(
            fingerprint_atual,
            musica_atual,
            pontos,
            bpm_atual,
            duracao_atual
        )

        if erro:
            mensagem = "Pontuação salva localmente. Envio online indisponível."
            mensagem_cor = COR_AMARELO
        else:
            mensagem = "Pontuação enviada ao ranking!"
            mensagem_cor = COR_VERDE

    else:
        mensagem = "Pontuação salva localmente. Faça login para enviar online."
        mensagem_cor = COR_AMARELO

    jogo_iniciado = False
    estado = "FIM_JOGO"


# ============================================================
# LOGIN
# ============================================================

def autenticar():
    global estado, mensagem, mensagem_cor

    usuario = usuario_digitado.strip()
    senha = senha_digitada

    if not usuario or not senha:
        mensagem = "Preencha nome e senha."
        mensagem_cor = COR_VERMELHO
        return

    resposta, erro = fazer_login(usuario, senha)

    if erro:
        mensagem = erro
        mensagem_cor = COR_VERMELHO
        return

    if not resposta or not resposta.get("token"):
        mensagem = "Resposta inválida do servidor."
        mensagem_cor = COR_VERMELHO
        return

    config["usuario"] = usuario
    config["token"] = resposta["token"]

    salvar_configuracoes()

    mensagem = "Login realizado!"
    mensagem_cor = COR_VERDE
    estado = "MODO_MENU"


def cadastrar():
    global estado, mensagem, mensagem_cor, campo_ativo

    usuario = usuario_digitado.strip()
    senha = senha_digitada

    if len(usuario) < 3:
        mensagem = "O nome precisa ter pelo menos 3 caracteres."
        mensagem_cor = COR_VERMELHO
        return

    if len(senha) < 6:
        mensagem = "A senha precisa ter pelo menos 6 caracteres."
        mensagem_cor = COR_VERMELHO
        return

    resposta, erro = registrar_usuario(usuario, senha)

    if erro:
        mensagem = erro
        mensagem_cor = COR_VERMELHO
        return

    mensagem = "Cadastro realizado! Agora faça login."
    mensagem_cor = COR_VERDE

    estado = "LOGIN"
    campo_ativo = "usuario"


# ============================================================
# RANKING
# ============================================================

def atualizar_ranking():
    global dados_ranking
    global mensagem
    global mensagem_cor

    if not fingerprint_atual:
        mensagem = "Escolha uma música primeiro."
        mensagem_cor = COR_VERMELHO
        return

    resposta, erro = buscar_ranking(fingerprint_atual)

    if erro:
        dados_ranking = []
        mensagem = "Não foi possível carregar o ranking."
        mensagem_cor = COR_VERMELHO
        return

    if isinstance(resposta, dict):
        dados_ranking = resposta.get("ranking", [])
    elif isinstance(resposta, list):
        dados_ranking = resposta
    else:
        dados_ranking = []


def desenhar_ranking():
    desenhar_texto(
        "RANKING DA MÚSICA",
        fonte_titulo,
        COR_AZUL,
        LARGURA // 2,
        60
    )

    desenhar_texto(
        musica_atual[:45] if musica_atual else "Nenhuma música selecionada",
        fonte_menu,
        COR_TEXTO,
        LARGURA // 2,
        125
    )

    if not config.get("token"):
        desenhar_texto(
            "Faça login para acessar o ranking online.",
            fonte_menu,
            COR_AMARELO,
            LARGURA // 2,
            190
        )

    elif not API_BASE_URL:
        desenhar_texto(
            "Servidor ainda não configurado.",
            fonte_menu,
            COR_AMARELO,
            LARGURA // 2,
            190
        )

    elif not dados_ranking:
        desenhar_texto(
            "Nenhuma pontuação encontrada.",
            fonte_menu,
            COR_SECUNDARIA,
            LARGURA // 2,
            230
        )

    else:
        desenhar_texto(
            "POSIÇÃO       JOGADOR                 PONTOS",
            fonte_menu,
            COR_AZUL,
            LARGURA // 2,
            200
        )

        for i, jogador in enumerate(dados_ranking[:10]):
            nome = str(jogador.get("username", "Jogador"))
            pontuacao = jogador.get("score", 0)

            linha = (
                f"{i + 1:02d}              "
                f"{nome[:20]:20s}     "
                f"{pontuacao}"
            )

            desenhar_texto(
                linha,
                fonte_menu,
                COR_AMARELO if i == 0 else COR_TEXTO,
                LARGURA // 2,
                250 + i * 38
            )

    desenhar_texto(
        "ENTER: atualizar    ESC: voltar",
        fonte_pequena,
        COR_SECUNDARIA,
        LARGURA // 2,
        ALTURA - 55
    )


# ============================================================
# CONFIGURAÇÃO DE TECLAS
# ============================================================

def desenhar_configuracao_teclas():
    desenhar_texto(
        "CONFIGURAR TECLAS",
        fonte_titulo,
        COR_AZUL,
        LARGURA // 2,
        70
    )

    desenhar_texto(
        "Escolha uma pista e pressione a tecla desejada.",
        fonte_menu,
        COR_SECUNDARIA,
        LARGURA // 2,
        150
    )

    for i in range(4):
        cor = COR_VERDE if i == indice_tecla_config else COR_TEXTO

        texto = f"PISTA {i + 1}: {nome_tecla(TECLAS[i])}"

        desenhar_texto(
            texto,
            fonte_hud,
            cor,
            LARGURA // 2,
            250 + i * 65
        )

    desenhar_texto(
        "Use as setas para escolher a pista.",
        fonte_pequena,
        COR_SECUNDARIA,
        LARGURA // 2,
        ALTURA - 110
    )

    desenhar_texto(
        "Pressione ESC para voltar.",
        fonte_pequena,
        COR_SECUNDARIA,
        LARGURA // 2,
        ALTURA - 75
    )


def configurar_tecla(nova_tecla):
    global mensagem, mensagem_cor

    if nova_tecla in TECLAS:
        mensagem = "Essa tecla já está sendo usada."
        mensagem_cor = COR_VERMELHO
        return

    TECLAS[indice_tecla_config] = nova_tecla

    salvar_configuracoes()

    mensagem = "Tecla alterada!"
    mensagem_cor = COR_VERDE


# ============================================================
# FUNÇÕES AUXILIARES DE DESENHO
# ============================================================

def desenhar_login():
    desenhar_texto(
        "LOGIN",
        fonte_titulo,
        COR_AZUL,
        LARGURA // 2,
        90
    )

    cor_usuario = COR_VERDE if campo_ativo == "usuario" else COR_TEXTO
    cor_senha = COR_VERDE if campo_ativo == "senha" else COR_TEXTO

    desenhar_texto(
        "Nome de usuário:",
        fonte_menu,
        cor_usuario,
        LARGURA // 2,
        230
    )

    desenhar_texto(
        usuario_digitado or "Digite seu nome",
        fonte_hud,
        cor_usuario,
        LARGURA // 2,
        270
    )

    desenhar_texto(
        "Senha:",
        fonte_menu,
        cor_senha,
        LARGURA // 2,
        350
    )

    desenhar_texto(
        "*" * len(senha_digitada) if senha_digitada else "Digite sua senha",
        fonte_hud,
        cor_senha,
        LARGURA // 2,
        390
    )

    desenhar_texto(
        "TAB: trocar campo | ENTER: entrar | ESC: voltar",
        fonte_pequena,
        COR_SECUNDARIA,
        LARGURA // 2,
        500
    )

    desenhar_texto(
        "F2: criar conta",
        fonte_pequena,
        COR_AZUL,
        LARGURA // 2,
        540
    )

    if mensagem:
        desenhar_texto(
            mensagem,
            fonte_pequena,
            mensagem_cor,
            LARGURA // 2,
            590
        )


def desenhar_cadastro():
    desenhar_texto(
        "CRIAR CONTA",
        fonte_titulo,
        COR_AZUL,
        LARGURA // 2,
        90
    )

    cor_usuario = COR_VERDE if campo_ativo == "usuario" else COR_TEXTO
    cor_senha = COR_VERDE if campo_ativo == "senha" else COR_TEXTO

    desenhar_texto(
        "Nome de usuário:",
        fonte_menu,
        cor_usuario,
        LARGURA // 2,
        230
    )

    desenhar_texto(
        usuario_digitado or "Digite seu nome",
        fonte_hud,
        cor_usuario,
        LARGURA // 2,
        270
    )

    desenhar_texto(
        "Senha:",
        fonte_menu,
        cor_senha,
        LARGURA // 2,
        350
    )

    desenhar_texto(
        "*" * len(senha_digitada) if senha_digitada else "Digite sua senha",
        fonte_hud,
        cor_senha,
        LARGURA // 2,
        390
    )

    desenhar_texto(
        "TAB: trocar campo | ENTER: cadastrar | ESC: voltar",
        fonte_pequena,
        COR_SECUNDARIA,
        LARGURA // 2,
        500
    )

    if mensagem:
        desenhar_texto(
            mensagem,
            fonte_pequena,
            mensagem_cor,
            LARGURA // 2,
            550
        )


# ============================================================
# INICIALIZAÇÃO
# ============================================================

rodando = True

while rodando:

    dt = relogio.tick(60) / 1000.0

    tela.fill(COR_FUNDO)

    for evento in pygame.event.get():

        if evento.type == pygame.QUIT:
            rodando = False

        elif evento.type == pygame.VIDEORESIZE and not tela_cheia:
            LARGURA = evento.w
            ALTURA = evento.h

        # ====================================================
        # ENTRADA DE TEXTO
        # ====================================================

        if evento.type == pygame.TEXTINPUT:

            if estado in ("LOGIN", "CADASTRO"):

                if campo_ativo == "usuario":
                    if len(usuario_digitado) < 24:
                        usuario_digitado += evento.text

                elif campo_ativo == "senha":
                    if len(senha_digitada) < 64:
                        senha_digitada += evento.text

        # ====================================================
        # TECLAS
        # ====================================================

        if evento.type == pygame.KEYDOWN:

            if evento.key == pygame.K_F11:
                alternar_tela_cheia()

            # ------------------------------------------------
            # MENU PRINCIPAL
            # ------------------------------------------------

            if estado == "MODO_MENU":

                opcoes = [
                    "Jogar",
                    "Ranking",
                    "Configurar teclas",
                    "Conta",
                    "Sair"
                ]

                if evento.key == pygame.K_DOWN:
                    indice_menu = (indice_menu + 1) % len(opcoes)

                elif evento.key == pygame.K_UP:
                    indice_menu = (indice_menu - 1) % len(opcoes)

                elif evento.key == pygame.K_RETURN:

                    escolha = opcoes[indice_menu]

                    if escolha == "Jogar":
                        indice_menu = 0
                        estado = "MUSICA_MENU"

                    elif escolha == "Ranking":

                        if config.get("token"):

                            if fingerprint_atual:
                                atualizar_ranking()
                                estado = "RANKING"

                            else:
                                mensagem = "Jogue uma música primeiro para abrir seu ranking."
                                mensagem_cor = COR_AMARELO

                        else:
                            mensagem = "Faça login para acessar o ranking."
                            mensagem_cor = COR_AMARELO

                    elif escolha == "Configurar teclas":
                        estado = "CONFIG_TECLAS"

                    elif escolha == "Conta":

                        if config.get("token"):
                            config["token"] = ""
                            config["usuario"] = ""
                            salvar_configuracoes()

                            mensagem = "Você saiu da conta."
                            mensagem_cor = COR_VERDE

                        else:
                            usuario_digitado = ""
                            senha_digitada = ""
                            campo_ativo = "usuario"
                            mensagem = ""
                            estado = "LOGIN"

                    elif escolha == "Sair":
                        rodando = False

            # ------------------------------------------------
            # SELEÇÃO DE MÚSICAS
            # ------------------------------------------------

            elif estado == "MUSICA_MENU":

                musicas = listar_musicas()

                if evento.key == pygame.K_ESCAPE:
                    indice_menu = 0
                    estado = "MODO_MENU"

                elif musicas:

                    if evento.key == pygame.K_DOWN:
                        indice_menu = (indice_menu + 1) % len(musicas)

                    elif evento.key == pygame.K_UP:
                        indice_menu = (indice_menu - 1) % len(musicas)

                    elif evento.key == pygame.K_RETURN:

                        escolhida = musicas[indice_menu]

                        tela.fill(COR_FUNDO)

                        desenhar_texto(
                            "ANALISANDO MÚSICA...",
                            fonte_hud,
                            COR_AMARELO,
                            LARGURA // 2,
                            ALTURA // 2
                        )

                        pygame.display.flip()

                        try:
                            iniciar_partida(escolhida)

                        except Exception as erro:
                            print("Erro ao iniciar música:", erro)
                            mensagem = "Erro ao carregar a música."
                            mensagem_cor = COR_VERMELHO
                            estado = "MUSICA_MENU"

            # ------------------------------------------------
            # JOGANDO
            # ------------------------------------------------

            elif estado == "JOGANDO":

                if evento.key == pygame.K_ESCAPE:
                    pygame.mixer.music.stop()

                    if cap is not None:
                        cap.release()
                        cap = None

                    jogo_iniciado = False
                    estado = "MODO_MENU"

                elif evento.key in TECLAS:

                    colunas_x, y_alvo = obter_layout()
                    indice = TECLAS.index(evento.key)
                    acertou = False

                    for nota in notas[:]:

                        distancia = abs(nota["y"] - y_alvo)

                        if (
                            nota["col"] == indice
                            and distancia <= 180
                        ):

                            notas.remove(nota)

                            if distancia <= 28:

                                pontos += 30 + (combo * 3)
                                vida = min(100, vida + 5)

                                feedback_texto = "PERFECT!"
                                feedback_cor = (50, 255, 220)

                            else:

                                pontos += 10 + combo
                                vida = min(100, vida + 2)

                                feedback_texto = "GOOD!"
                                feedback_cor = COR_AMARELO

                            combo += 1
                            feedback_timer = 0.6
                            acertou = True
                            break

                    if not acertou:

                        erros += 1
                        vida = max(0, vida - 10)
                        combo = 0

                        feedback_texto = "MISS!"
                        feedback_cor = COR_VERMELHO
                        feedback_timer = 0.5

                        if vida <= 0:
                            pygame.mixer.music.stop()

            # ------------------------------------------------
            # FIM DE JOGO
            # ------------------------------------------------

            elif estado == "FIM_JOGO":

                if evento.key in (
                    pygame.K_RETURN,
                    pygame.K_ESCAPE
                ):
                    estado = "MODO_MENU"

            # ------------------------------------------------
            # CONFIGURAÇÃO DE TECLAS
            # ------------------------------------------------

            elif estado == "CONFIG_TECLAS":

                if evento.key == pygame.K_ESCAPE:
                    estado = "MODO_MENU"

                elif evento.key == pygame.K_DOWN:
                    indice_tecla_config = (indice_tecla_config + 1) % 4

                elif evento.key == pygame.K_UP:
                    indice_tecla_config = (indice_tecla_config - 1) % 4

                elif evento.key not in (
                    pygame.K_RETURN,
                    pygame.K_ESCAPE,
                    pygame.K_F11
                ):
                    configurar_tecla(evento.key)

            # ------------------------------------------------
            # LOGIN E CADASTRO
            # ------------------------------------------------

            elif estado in ("LOGIN", "CADASTRO"):

                if estado == "LOGIN" and evento.key == pygame.K_F2:
                    usuario_digitado = ""
                    senha_digitada = ""
                    campo_ativo = "usuario"
                    mensagem = ""
                    estado = "CADASTRO"

                elif evento.key == pygame.K_ESCAPE:
                    estado = "MODO_MENU"

                elif evento.key == pygame.K_TAB:
                    campo_ativo = (
                        "senha"
                        if campo_ativo == "usuario"
                        else "usuario"
                    )

                elif evento.key == pygame.K_BACKSPACE:

                    if campo_ativo == "usuario":
                        usuario_digitado = usuario_digitado[:-1]
                    else:
                        senha_digitada = senha_digitada[:-1]

                elif evento.key == pygame.K_RETURN:

                    if estado == "LOGIN":
                        autenticar()
                    else:
                        cadastrar()

            # ------------------------------------------------
            # RANKING
            # ------------------------------------------------

            elif estado == "RANKING":

                if evento.key == pygame.K_ESCAPE:
                    estado = "MODO_MENU"

                elif evento.key == pygame.K_RETURN:
                    atualizar_ranking()

    # ========================================================
    # DESENHO DO MENU
    # ========================================================

    if estado == "MODO_MENU":

        desenhar_texto(
            "NEON BEAT",
            fonte_titulo,
            COR_AZUL,
            LARGURA // 2,
            80
        )

        opcoes = [
            "Jogar",
            "Ranking",
            "Configurar teclas",
            "Conta",
            "Sair"
        ]

        for i, opcao in enumerate(opcoes):

            cor = COR_VERDE if i == indice_menu else COR_TEXTO
            prefixo = "> " if i == indice_menu else "  "

            desenhar_texto(
                prefixo + opcao,
                fonte_hud,
                cor,
                LARGURA // 2,
                230 + i * 65
            )

        usuario = config.get("usuario")

        if usuario:
            texto_conta = "Conta: " + usuario
        else:
            texto_conta = "Você não está conectado."

        desenhar_texto(
            texto_conta,
            fonte_pequena,
            COR_SECUNDARIA,
            LARGURA // 2,
            ALTURA - 90
        )

        desenhar_texto(
            "[F11] Tela cheia | [SETAS] Navegar | [ENTER] Selecionar",
            fonte_pequena,
            COR_SECUNDARIA,
            LARGURA // 2,
            ALTURA - 50
        )

    # ========================================================
    # SELEÇÃO DE MÚSICAS
    # ========================================================

    elif estado == "MUSICA_MENU":

        desenhar_texto(
            "ESCOLHA A MÚSICA",
            fonte_titulo,
            COR_AZUL,
            LARGURA // 2,
            60
        )

        musicas = listar_musicas()

        if not musicas:

            desenhar_texto(
                "Coloque arquivos MP3 ou MP4 na pasta musicas.",
                fonte_menu,
                COR_VERMELHO,
                LARGURA // 2,
                250
            )

        else:

            altura_linha = 45
            topo_lista = 145

            musicas_visiveis = max(
                1,
                (ALTURA - 230) // altura_linha
            )

            if indice_menu >= len(musicas):
                indice_menu = 0

            if indice_menu < rolagem_musicas:
                rolagem_musicas = indice_menu

            if indice_menu >= rolagem_musicas + musicas_visiveis:
                rolagem_musicas = indice_menu - musicas_visiveis + 1

            area_recorte = pygame.Rect(
                0,
                topo_lista,
                LARGURA,
                ALTURA - 230
            )

            tela.set_clip(area_recorte)

            fim_lista = min(
                len(musicas),
                rolagem_musicas + musicas_visiveis
            )

            for i in range(rolagem_musicas, fim_lista):

                musica = musicas[i]
                cor = COR_VERDE if i == indice_menu else COR_TEXTO
                prefixo = "> " if i == indice_menu else "  "

                desenhar_texto(
                    prefixo + musica[:40],
                    fonte_menu,
                    cor,
                    LARGURA // 2,
                    topo_lista + (i - rolagem_musicas) * altura_linha
                )

            tela.set_clip(None)

        desenhar_texto(
            "SETAS: navegar | ENTER: jogar | ESC: voltar",
            fonte_pequena,
            COR_SECUNDARIA,
            LARGURA // 2,
            ALTURA - 45
        )

    # ========================================================
    # CONFIGURAÇÃO DE TECLAS
    # ========================================================

    elif estado == "CONFIG_TECLAS":
        desenhar_configuracao_teclas()

    # ========================================================
    # LOGIN
    # ========================================================

    elif estado == "LOGIN":
        desenhar_login()

    # ========================================================
    # CADASTRO
    # ========================================================

    elif estado == "CADASTRO":
        desenhar_cadastro()

    # ========================================================
    # RANKING
    # ========================================================

    elif estado == "RANKING":
        desenhar_ranking()

    # ========================================================
    # JOGANDO
    # ========================================================

    elif estado == "JOGANDO":

        colunas_x, y_alvo = obter_layout()

        tempo_ms = pygame.mixer.music.get_pos()
        tempo_musica = max(0, tempo_ms / 1000.0)

        if tem_video and cap is not None:

            frame_esperado = int(tempo_musica * fps_video)

            while frame_atual_video < frame_esperado:

                ret, frame = cap.read()
                frame_atual_video += 1

                if not ret:
                    break

                frame = cv2.resize(
                    frame,
                    (LARGURA, ALTURA)
                )

                frame = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2RGB
                )

                ultimo_frame_surface = pygame.surfarray.make_surface(
                    frame.swapaxes(0, 1)
                )

            if ultimo_frame_surface is not None:
                tela.blit(ultimo_frame_surface, (0, 0))

        overlay = pygame.Surface((LARGURA, ALTURA))
        overlay.set_alpha(140)
        overlay.fill((0, 0, 0))
        tela.blit(overlay, (0, 0))

        if not pygame.mixer.music.get_busy() and jogo_iniciado:
            finalizar_partida()

        VELOCIDADE = 630.0 * (bpm_atual / 80.0)
        distancia_ate_alvo = y_alvo + RAIO_NOTA
        tempo_queda = distancia_ate_alvo / VELOCIDADE

        for item in mapa_notas:

            if (
                not item["spawnada"]
                and tempo_musica >= item["tempo_alvo"] - tempo_queda
            ):

                notas.append({
                    "col": item["col"],
                    "y": -float(RAIO_NOTA)
                })

                item["spawnada"] = True

        # Pistas

        for i in range(4):

            pygame.draw.circle(
                tela,
                CORES[i],
                (colunas_x[i], y_alvo),
                RAIO_NOTA,
                4
            )

            texto_tecla = fonte_teclas.render(
                nome_tecla(TECLAS[i]),
                True,
                COR_TEXTO
            )

            tela.blit(
                texto_tecla,
                (
                    colunas_x[i] - texto_tecla.get_width() // 2,
                    y_alvo - texto_tecla.get_height() // 2
                )
            )

        # Notas

        for nota in notas[:]:

            nota["y"] += VELOCIDADE * dt

            cx = colunas_x[nota["col"]]
            cy = int(nota["y"])

            pygame.draw.circle(
                tela,
                CORES[nota["col"]],
                (cx, cy),
                RAIO_NOTA
            )

            pygame.draw.circle(
                tela,
                (255, 255, 255),
                (cx, cy),
                RAIO_NOTA - 12
            )

            if nota["y"] > ALTURA + RAIO_NOTA:

                notas.remove(nota)

                erros += 1
                vida = max(0, vida - 10)
                combo = 0

                feedback_texto = "MISS!"
                feedback_cor = COR_VERMELHO
                feedback_timer = 0.5

                if vida <= 0:
                    pygame.mixer.music.stop()

        # Feedback

        if feedback_timer > 0:

            feedback_timer -= dt

            desenhar_texto(
                feedback_texto,
                fonte_feedback,
                feedback_cor,
                LARGURA // 2,
                y_alvo - 100
            )

        # HUD

        tela.blit(
            fonte_hud.render(
                f"Pontos: {pontos}",
                True,
                COR_TEXTO
            ),
            (30, 30)
        )

        tela.blit(
            fonte_hud.render(
                f"Combo: {combo}x",
                True,
                COR_AMARELO
            ),
            (30, 65)
        )

        tela.blit(
            fonte_menu.render(
                f"BPM: {int(bpm_atual)}",
                True,
                COR_AZUL
            ),
            (30, 100)
        )

        # Barra de vida

        largura_barra = 220
        altura_barra = 22

        x_barra = 30
        y_barra = 135

        pygame.draw.rect(
            tela,
            (65, 65, 75),
            (
                x_barra,
                y_barra,
                largura_barra,
                altura_barra
            ),
            border_radius=6
        )

        if vida > 50:
            cor_vida = COR_VERDE
        elif vida > 25:
            cor_vida = COR_AMARELO
        else:
            cor_vida = COR_VERMELHO

        largura_preenchida = int(largura_barra * vida / 100)

        if largura_preenchida > 0:

            pygame.draw.rect(
                tela,
                cor_vida,
                (
                    x_barra,
                    y_barra,
                    largura_preenchida,
                    altura_barra
                ),
                border_radius=6
            )

        pygame.draw.rect(
            tela,
            COR_TEXTO,
            (
                x_barra,
                y_barra,
                largura_barra,
                altura_barra
            ),
            width=2,
            border_radius=6
        )

        desenhar_texto(
            f"VIDA: {vida}/100",
            fonte_pequena,
            COR_TEXTO,
            x_barra + largura_barra + 60,
            y_barra + 2
        )

        desenhar_texto(
            "ESC: sair da partida",
            fonte_pequena,
            COR_SECUNDARIA,
            LARGURA // 2,
            20
        )

    # ========================================================
    # FIM DE JOGO
    # ========================================================

    elif estado == "FIM_JOGO":

        desenhar_texto(
            "FIM DA MÚSICA!",
            fonte_titulo,
            COR_AZUL,
            LARGURA // 2,
            100
        )

        desenhar_texto(
            musica_atual[:45],
            fonte_menu,
            COR_TEXTO,
            LARGURA // 2,
            175
        )

        desenhar_texto(
            f"Pontuação final: {pontos}",
            fonte_hud,
            COR_VERDE,
            LARGURA // 2,
            250
        )

        desenhar_texto(
            f"Erros: {erros}",
            fonte_hud,
            COR_VERMELHO,
            LARGURA // 2,
            300
        )

        recorde_atual = recordes.get(fingerprint_atual, 0)

        desenhar_texto(
            f"Recorde local: {recorde_atual}",
            fonte_hud,
            COR_AMARELO,
            LARGURA // 2,
            350
        )

        desenhar_texto(
            mensagem,
            fonte_pequena,
            mensagem_cor,
            LARGURA // 2,
            420
        )

        desenhar_texto(
            "Pressione ENTER para voltar ao menu.",
            fonte_menu,
            COR_TEXTO,
            LARGURA // 2,
            510
        )

        desenhar_texto(
            "O ranking online depende da conexão com o servidor.",
            fonte_pequena,
            COR_SECUNDARIA,
            LARGURA // 2,
            555
        )

    # ========================================================
    # MENSAGENS GERAIS
    # ========================================================

    if mensagem and estado not in (
        "LOGIN",
        "CADASTRO",
        "FIM_JOGO"
    ):

        desenhar_texto(
            mensagem,
            fonte_pequena,
            mensagem_cor,
            LARGURA // 2,
            ALTURA - 25
        )

    pygame.display.flip()


# ============================================================
# ENCERRAMENTO
# ============================================================

pygame.mixer.music.stop()

if cap is not None:
    cap.release()

pygame.quit()