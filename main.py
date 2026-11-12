import pygame
import random
import os
import cv2
import socket
import threading
import json
import librosa
import numpy as np
from moviepy import VideoFileClip

pygame.init()
pygame.mixer.init()

LARGURA, ALTURA = 800, 700
tela = pygame.display.set_mode((LARGURA, ALTURA), pygame.RESIZABLE)
pygame.display.set_caption("Neon Beat - Beatmap Automático")
relogio = pygame.time.Clock()
tela_cheia = False

COR_FUNDO = (18, 18, 28)
CORES = [(255, 50, 100), (50, 200, 255), (50, 255, 100), (255, 200, 50)]
TECLAS = [pygame.K_a, pygame.K_s, pygame.K_j, pygame.K_k]
NOMES_TECLAS = ["A", "S", "J", "K"]
RAIO_NOTA = 46  # Teclas e notas um pouco maiores

fonte_titulo = pygame.font.SysFont("Arial", 46, bold=True)
fonte_menu = pygame.font.SysFont("Arial", 22)
fonte_hud = pygame.font.SysFont("Arial", 26, bold=True)
fonte_feedback = pygame.font.SysFont("Arial", 32, bold=True)
fonte_teclas = pygame.font.SysFont("Arial", 30, bold=True)

PASTA_MUSICAS = "musicas"
PASTA_CACHE = "cache_audio"
os.makedirs(PASTA_MUSICAS, exist_ok=True)
os.makedirs(PASTA_CACHE, exist_ok=True)

def listar_musicas():
    return sorted([f for f in os.listdir(PASTA_MUSICAS) if f.endswith((".mp3", ".mp4"))])

def alternar_tela_cheia():
    global tela, LARGURA, ALTURA, tela_cheia
    tela_cheia = not tela_cheia
    if tela_cheia:
        tela = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        tela = pygame.display.set_mode((800, 700), pygame.RESIZABLE)
    LARGURA, ALTURA = tela.get_size()

def obter_layout():
    centro_x = LARGURA // 2
    espacamento = 120
    colunas_x = [
        centro_x - int(espacamento * 1.5),
        centro_x - int(espacamento * 0.5),
        centro_x + int(espacamento * 0.5),
        centro_x + int(espacamento * 1.5),
    ]
    y_alvo = ALTURA - 100
    return colunas_x, y_alvo

def mapear_musica(caminho_audio, nome_base):
    # Cache novo para forçar a geração do mapa com maior densidade rítmica.
    arquivo_json = os.path.join(PASTA_CACHE, nome_base + "_beatmap_ritmo_v7.json")
    if os.path.exists(arquivo_json):
        with open(arquivo_json, "r", encoding="utf-8") as f:
            dados = json.load(f)
        for item in dados["notas"]:
            item["spawnada"] = False
        return dados["notas"], dados["bpm"]

    y, sr = librosa.load(caminho_audio, sr=22050, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

    # O Librosa pode retornar o BPM como array NumPy.
    tempo_array = np.asarray(tempo).reshape(-1)
    bpm = float(tempo_array[0]) if tempo_array.size else 120.0
    bpm = max(40.0, min(bpm, 300.0))

    # Mantém os ataques detectados na música.
    onsets_frames = librosa.onset.onset_detect(
        y=y, sr=sr, wait=6, pre_avg=4, post_avg=4
    )
    tempos_onsets = librosa.frames_to_time(onsets_frames, sr=sr)

    # Adiciona batidas e contratempos (meio tempo entre batidas).
    # Isso aumenta a quantidade de notas sem colocá-las em momentos aleatórios.
    tempos_batidas = librosa.frames_to_time(beat_frames, sr=sr)
    tempos_grade = []

    for tempo_batida in tempos_batidas:
        tempos_grade.append(float(tempo_batida))

    for i in range(len(tempos_batidas) - 1):
        inicio = float(tempos_batidas[i])
        fim = float(tempos_batidas[i + 1])
        if fim > inicio:
            tempos_grade.append((inicio + fim) / 2.0)

    # Junta os ataques originais com a grade rítmica e remove eventos
    # muito próximos, evitando uma chuva de notas impossível de jogar.
    tempos_candidatos = sorted(
        float(t) for t in list(tempos_onsets) + tempos_grade
        if float(t) >= 1.5
    )

    tempos_notas = []
    intervalo_minimo = 0.11
    for instante in tempos_candidatos:
        if not tempos_notas or instante - tempos_notas[-1] >= intervalo_minimo:
            tempos_notas.append(instante)

    mapa_notas = []
    ultima_coluna = None
    fila_colunas = []

    for tempo_seg in tempos_notas:
        # Embaralha as quatro pistas em ciclos para distribuir as notas
        # de forma equilibrada, sem deixar o padrão preso em uma tecla.
        if not fila_colunas:
            fila_colunas = [0, 1, 2, 3]
            random.shuffle(fila_colunas)

            # Evita repetir a mesma pista na virada de um ciclo.
            if len(fila_colunas) > 1 and fila_colunas[0] == ultima_coluna:
                fila_colunas[0], fila_colunas[1] = fila_colunas[1], fila_colunas[0]

        col = fila_colunas.pop(0)
        ultima_coluna = col
        mapa_notas.append({
            "tempo_alvo": float(tempo_seg),
            "col": col,
            "spawnada": False
        })

    with open(arquivo_json, "w", encoding="utf-8") as f:
        json.dump({"bpm": bpm, "notas": mapa_notas}, f)

    return mapa_notas, bpm

# --- REDE / MULTIPLAYER ---
PORTA = 5555
sock_rede = None
pontos_oponente = 0
status_rede = ""
ip_digitado = "127.0.0.1"

def enviar_pacote(conn, tipo, dados_dict=None, bytes_arquivo=None):
    cabecalho = {"tipo": tipo}
    if dados_dict:
        cabecalho.update(dados_dict)
    if bytes_arquivo is not None:
        cabecalho["tamanho_arquivo"] = len(bytes_arquivo)
    msg_json = (json.dumps(cabecalho) + "\n").encode("utf-8")
    conn.sendall(msg_json)
    if bytes_arquivo is not None:
        conn.sendall(bytes_arquivo)

def ler_linha_socket(conn):
    buffer = b""
    while not buffer.endswith(b"\n"):
        dado = conn.recv(1)
        if not dado:
            return None
        buffer += dado
    return json.loads(buffer.decode("utf-8"))

def thread_escuta_jogo(conn):
    global pontos_oponente
    try:
        while estado == "JOGANDO":
            msg = ler_linha_socket(conn)
            if not msg:
                break
            if msg.get("tipo") == "PONTOS":
                pontos_oponente = msg.get("valor", 0)
    except:
        pass

def iniciar_host_thread(nome_musica):
    global status_rede, sock_rede
    try:
        servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        servidor.bind(("0.0.0.0", PORTA))
        servidor.listen(1)
        status_rede = f"Aguardando Player 2 na porta {PORTA}..."
        conn, addr = servidor.accept()
        sock_rede = conn
        status_rede = f"Player 2 conectado ({addr})! Verificando música..."
        enviar_pacote(conn, "CHECK_MUSICA", {"arquivo": nome_musica})
        resposta = ler_linha_socket(conn)
        if resposta and not resposta.get("tem"):
            status_rede = "Enviando música para o Player 2..."
            caminho = os.path.join(PASTA_MUSICAS, nome_musica)
            with open(caminho, "rb") as f:
                dados = f.read()
            enviar_pacote(conn, "DOWNLOAD_MUSICA", {"arquivo": nome_musica}, dados)
            ler_linha_socket(conn)
        status_rede = "Sincronizando batidas..."
        enviar_pacote(conn, "START", {"arquivo": nome_musica})
        iniciar_partida(nome_musica, online=True)
    except Exception as e:
        status_rede = f"Erro no Host: {e}"

def conectar_cliente_thread(ip):
    global status_rede, sock_rede
    try:
        status_rede = f"Conectando a {ip}..."
        cliente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cliente.connect((ip, PORTA))
        sock_rede = cliente
        status_rede = "Conectado! Aguardando Host..."
        while True:
            msg = ler_linha_socket(cliente)
            if not msg:
                break
            tipo = msg.get("tipo")
            if tipo == "CHECK_MUSICA":
                arq = msg["arquivo"]
                existe = os.path.exists(os.path.join(PASTA_MUSICAS, arq))
                enviar_pacote(cliente, "RESP_MUSICA", {"tem": existe})
                if not existe:
                    status_rede = f"Baixando {arq} do Host..."
            elif tipo == "DOWNLOAD_MUSICA":
                arq = msg["arquivo"]
                tam = msg["tamanho_arquivo"]
                recebido = bytearray()
                while len(recebido) < tam:
                    chunk = cliente.recv(min(65536, tam - len(recebido)))
                    if not chunk:
                        break
                    recebido.extend(chunk)
                with open(os.path.join(PASTA_MUSICAS, arq), "wb") as f:
                    f.write(recebido)
                status_rede = "Download concluído!"
                enviar_pacote(cliente, "DOWNLOAD_OK")
            elif tipo == "START":
                arq = msg["arquivo"]
                status_rede = "Sincronizando batidas..."
                iniciar_partida(arq, online=True)
                break
    except Exception as e:
        status_rede = f"Falha ao conectar: {e}"

estado = "MODO_MENU"
modo_atual = "OFFLINE"
indice_menu = 0
cap = None
tem_video = False
fps_video = 30
frame_atual_video = 0
ultimo_frame_surface = None

notas = []
mapa_notas = []
bpm_atual = 120.0
pontos = 0
combo = 0
jogo_iniciado = False
feedback_texto = ""
feedback_cor = (255, 255, 255)
feedback_timer = 0.0

def iniciar_partida(nome_arquivo, online=False):
    global estado, cap, tem_video, fps_video, frame_atual_video, ultimo_frame_surface
    global notas, mapa_notas, bpm_atual, pontos, combo, pontos_oponente, jogo_iniciado, feedback_texto

    caminho_completo = os.path.join(PASTA_MUSICAS, nome_arquivo)
    notas = []
    pontos = 0
    combo = 0
    pontos_oponente = 0
    feedback_texto = ""
    jogo_iniciado = False
    tem_video = False
    frame_atual_video = 0
    ultimo_frame_surface = None

    if cap is not None:
        cap.release()
        cap = None

    if nome_arquivo.endswith(".mp4"):
        tem_video = True
        arquivo_audio = os.path.join(PASTA_CACHE, nome_arquivo + ".mp3")
        if not os.path.exists(arquivo_audio):
            clip = VideoFileClip(caminho_completo)
            clip.audio.write_audiofile(arquivo_audio, logger=None)
            clip.close()
        cap = cv2.VideoCapture(caminho_completo)
        fps_video = cap.get(cv2.CAP_PROP_FPS) or 30
    else:
        arquivo_audio = caminho_completo

    mapa_notas, bpm_atual = mapear_musica(arquivo_audio, nome_arquivo)
    pygame.mixer.music.load(arquivo_audio)
    pygame.mixer.music.play()
    jogo_iniciado = True
    estado = "JOGANDO"

    if online and sock_rede:
        threading.Thread(target=thread_escuta_jogo, args=(sock_rede,), daemon=True).start()

rodando = True

while rodando:
    dt = relogio.tick(60) / 1000.0
    tela.fill(COR_FUNDO)

    for evento in pygame.event.get():
        if evento.type == pygame.QUIT:
            rodando = False

        elif evento.type == pygame.VIDEORESIZE and not tela_cheia:
            LARGURA, ALTURA = evento.w, evento.h

        elif evento.type == pygame.KEYDOWN:
            if evento.key == pygame.K_F11:
                alternar_tela_cheia()

            if estado == "MODO_MENU":
                opcoes = [
                    "1. Jogar Offline (Solo)",
                    "2. Criar Sala Online (Host)",
                    "3. Entrar em Sala Online (IP)"
                ]

                if evento.key == pygame.K_DOWN:
                    indice_menu = (indice_menu + 1) % len(opcoes)

                elif evento.key == pygame.K_UP:
                    indice_menu = (indice_menu - 1) % len(opcoes)

                elif evento.key == pygame.K_RETURN:
                    if indice_menu == 0:
                        modo_atual = "OFFLINE"
                        indice_menu = 0
                        estado = "MUSICA_MENU"

                    elif indice_menu == 1:
                        modo_atual = "ONLINE_HOST"
                        indice_menu = 0
                        estado = "MUSICA_MENU"

                    elif indice_menu == 2:
                        modo_atual = "ONLINE_CLIENT"
                        status_rede = ""
                        estado = "DIGITANDO_IP"

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
                        aviso = fonte_hud.render(
                            "Analisando ritmo da música, aguarde...",
                            True,
                            (255, 220, 50)
                        )
                        tela.blit(
                            aviso,
                            (
                                LARGURA // 2 - aviso.get_width() // 2,
                                ALTURA // 2
                            )
                        )
                        pygame.display.flip()

                        if modo_atual == "OFFLINE":
                            iniciar_partida(escolhida, online=False)
                        else:
                            estado = "ONLINE_LOBBY"
                            threading.Thread(
                                target=iniciar_host_thread,
                                args=(escolhida,),
                                daemon=True
                            ).start()

            elif estado == "DIGITANDO_IP":
                if evento.key == pygame.K_ESCAPE:
                    estado = "MODO_MENU"

                elif evento.key == pygame.K_BACKSPACE:
                    ip_digitado = ip_digitado[:-1]

                elif evento.key == pygame.K_RETURN:
                    estado = "ONLINE_LOBBY"
                    threading.Thread(
                        target=conectar_cliente_thread,
                        args=(ip_digitado,),
                        daemon=True
                    ).start()

                elif evento.unicode in "0123456789.":
                    ip_digitado += evento.unicode

            elif estado == "ONLINE_LOBBY":
                if evento.key == pygame.K_ESCAPE:
                    if sock_rede:
                        try:
                            sock_rede.close()
                        except OSError:
                            pass
                    estado = "MODO_MENU"

            elif estado == "JOGANDO":
                if evento.key == pygame.K_ESCAPE:
                    pygame.mixer.music.stop()

                    if sock_rede:
                        try:
                            sock_rede.close()
                        except OSError:
                            pass

                    estado = "MODO_MENU"

                elif evento.key in TECLAS:
                    colunas_x, y_alvo = obter_layout()
                    indice = TECLAS.index(evento.key)
                    acertou = False

                    for nota in notas[:]:
                        distancia = abs(nota["y"] - y_alvo)

                        # Aceita o acerto quando as duas notas circulares se sobrepoem.
                        # Com raio 46, a janela total fica em 92 px.
                        if nota["col"] == indice and distancia <= RAIO_NOTA * 2:
                            notas.remove(nota)

                            if distancia <= 28:
                                pontos += 30 + (combo * 3)
                                feedback_texto = "PERFECT!"
                                feedback_cor = (50, 255, 220)
                            else:
                                pontos += 10 + combo
                                feedback_texto = "GOOD"
                                feedback_cor = (255, 220, 50)

                            combo += 1
                            feedback_timer = 0.6
                            acertou = True

                            if modo_atual != "OFFLINE" and sock_rede:
                                try:
                                    enviar_pacote(
                                        sock_rede,
                                        "PONTOS",
                                        {"valor": pontos}
                                    )
                                except OSError:
                                    pass

                            break

                    if not acertou:
                        combo = 0
                        feedback_texto = "MISS"
                        feedback_cor = (255, 60, 60)
                        feedback_timer = 0.5

            elif estado == "FIM_JOGO":
                if evento.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    if sock_rede:
                        try:
                            sock_rede.close()
                        except OSError:
                            pass
                    estado = "MODO_MENU"

    # ==========================================
    # DESENHO DAS TELAS
    # ==========================================

    if estado == "MODO_MENU":
        titulo = fonte_titulo.render("NEON BEAT", True, (50, 200, 255))
        dica = fonte_menu.render(
            "[F11] Tela Cheia  |  [SETAS] Navegar  |  [ENTER] Selecionar",
            True,
            (150, 150, 170)
        )

        tela.blit(
            titulo,
            (LARGURA // 2 - titulo.get_width() // 2, 80)
        )
        tela.blit(
            dica,
            (LARGURA // 2 - dica.get_width() // 2, ALTURA - 50)
        )

        opcoes = [
            "Jogar Offline (Solo)",
            "Criar Sala Online (Host)",
            "Entrar em Sala Online (IP)"
        ]

        for idx, op in enumerate(opcoes):
            cor = (50, 255, 100) if idx == indice_menu else (255, 255, 255)
            prefixo = "> " if idx == indice_menu else "   "
            txt = fonte_hud.render(prefixo + op, True, cor)
            tela.blit(
                txt,
                (LARGURA // 2 - txt.get_width() // 2, 240 + idx * 60)
            )

    elif estado == "MUSICA_MENU":
        titulo = fonte_titulo.render(
            "ESCOLHA A MÚSICA",
            True,
            (50, 200, 255)
        )
        tela.blit(
            titulo,
            (LARGURA // 2 - titulo.get_width() // 2, 60)
        )

        musicas = listar_musicas()

        if not musicas:
            aviso = fonte_menu.render(
                "Coloque arquivos .mp3 ou .mp4 na pasta 'musicas'!",
                True,
                (255, 80, 80)
            )
            tela.blit(
                aviso,
                (LARGURA // 2 - aviso.get_width() // 2, 250)
            )
        else:
            for idx, musica in enumerate(musicas):
                cor = (50, 255, 100) if idx == indice_menu else (255, 255, 255)
                prefixo = "> " if idx == indice_menu else "   "
                txt = fonte_menu.render(
                    prefixo + musica[:45],
                    True,
                    cor
                )
                tela.blit(txt, (LARGURA // 2 - 220, 160 + idx * 40))

    elif estado == "DIGITANDO_IP":
        titulo = fonte_titulo.render(
            "DIGITE O IP DO HOST",
            True,
            (50, 200, 255)
        )
        caixa = fonte_hud.render(
            f"IP: {ip_digitado}_",
            True,
            (50, 255, 100)
        )
        dica = fonte_menu.render(
            "Pressione ENTER para conectar ou ESC para voltar",
            True,
            (180, 180, 180)
        )

        tela.blit(
            titulo,
            (LARGURA // 2 - titulo.get_width() // 2, 150)
        )
        tela.blit(
            caixa,
            (LARGURA // 2 - caixa.get_width() // 2, 260)
        )
        tela.blit(
            dica,
            (LARGURA // 2 - dica.get_width() // 2, 340)
        )

    elif estado == "ONLINE_LOBBY":
        titulo = fonte_titulo.render(
            "SALA ONLINE",
            True,
            (50, 200, 255)
        )
        st = fonte_hud.render(
            status_rede,
            True,
            (255, 220, 50)
        )
        dica = fonte_menu.render(
            "Pressione ESC para cancelar",
            True,
            (180, 180, 180)
        )

        tela.blit(
            titulo,
            (LARGURA // 2 - titulo.get_width() // 2, 150)
        )
        tela.blit(
            st,
            (LARGURA // 2 - st.get_width() // 2, 260)
        )
        tela.blit(
            dica,
            (LARGURA // 2 - dica.get_width() // 2, 340)
        )

    elif estado == "JOGANDO":
        colunas_x, y_alvo = obter_layout()
        tempo_ms = pygame.mixer.music.get_pos()
        tempo_musica = tempo_ms / 1000.0

        if tem_video and cap is not None:
            frame_esperado = int(tempo_musica * fps_video)

            while frame_atual_video < frame_esperado:
                ret, frame = cap.read()
                frame_atual_video += 1

                if not ret:
                    break

                if frame_atual_video == frame_esperado:
                    frame = cv2.resize(frame, (LARGURA, ALTURA))
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
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
            estado = "FIM_JOGO"

        # A velocidade acompanha o BPM: 80 BPM = 630 px/s.
        # A escala foi aumentada em 50% para deixar a jogabilidade mais rápida.
        # O spawn usa a mesma velocidade para manter a chegada sincronizada.
        VELOCIDADE = 630.0 * (bpm_atual / 80.0)
        distancia_ate_alvo = y_alvo + RAIO_NOTA
        tempo_queda = distancia_ate_alvo / VELOCIDADE

        for item in mapa_notas:
            if (
                not item["spawnada"]
                and tempo_musica >= (item["tempo_alvo"] - tempo_queda)
            ):
                notas.append({
                    "col": item["col"],
                    "y": -float(RAIO_NOTA)
                })
                item["spawnada"] = True

        for i in range(4):
            pygame.draw.circle(
                tela,
                CORES[i],
                (colunas_x[i], y_alvo),
                RAIO_NOTA,
                4
            )

            txt_tecla = fonte_teclas.render(
                NOMES_TECLAS[i],
                True,
                (230, 230, 240)
            )
            tela.blit(
                txt_tecla,
                (
                    colunas_x[i] - txt_tecla.get_width() // 2,
                    y_alvo - txt_tecla.get_height() // 2
                )
            )

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
                combo = 0
                feedback_texto = "MISS"
                feedback_cor = (255, 60, 60)
                feedback_timer = 0.5

        if feedback_timer > 0:
            feedback_timer -= dt
            txt_fb = fonte_feedback.render(
                feedback_texto,
                True,
                feedback_cor
            )
            tela.blit(
                txt_fb,
                (LARGURA // 2 - txt_fb.get_width() // 2, y_alvo - 100)
            )

        tela.blit(
            fonte_hud.render(
                f"Seus Pontos: {pontos}",
                True,
                (255, 255, 255)
            ),
            (30, 30)
        )
        tela.blit(
            fonte_hud.render(
                f"Combo: {combo}x",
                True,
                (255, 220, 50)
            ),
            (30, 65)
        )
        tela.blit(
            fonte_menu.render(
                f"BPM: {int(bpm_atual)}",
                True,
                (150, 220, 255)
            ),
            (30, 100)
        )

        if modo_atual != "OFFLINE":
            tela.blit(
                fonte_hud.render(
                    f"Player 2: {pontos_oponente}",
                    True,
                    (255, 100, 100)
                ),
                (LARGURA - 240, 30)
            )

    elif estado == "FIM_JOGO":
        titulo = fonte_titulo.render(
            "FIM DA MÚSICA!",
            True,
            (50, 200, 255)
        )
        tela.blit(
            titulo,
            (LARGURA // 2 - titulo.get_width() // 2, 120)
        )

        if modo_atual == "OFFLINE":
            res = fonte_hud.render(
                f"Pontuação Final: {pontos}",
                True,
                (50, 255, 100)
            )
            tela.blit(
                res,
                (LARGURA // 2 - res.get_width() // 2, 250)
            )
        else:
            if pontos > pontos_oponente:
                vencedor, cor_v = "VOCÊ VENCEU!", (50, 255, 100)
            elif pontos < pontos_oponente:
                vencedor, cor_v = "PLAYER 2 VENCEU!", (255, 80, 80)
            else:
                vencedor, cor_v = "EMPATE!", (255, 220, 50)

            txt_v = fonte_titulo.render(vencedor, True, cor_v)
            txt_p = fonte_hud.render(
                f"Você: {pontos}  vs  Oponente: {pontos_oponente}",
                True,
                (255, 255, 255)
            )

            tela.blit(
                txt_v,
                (LARGURA // 2 - txt_v.get_width() // 2, 210)
            )
            tela.blit(
                txt_p,
                (LARGURA // 2 - txt_p.get_width() // 2, 300)
            )

        dica = fonte_menu.render(
            "Pressione ENTER para voltar ao menu",
            True,
            (180, 180, 180)
        )
        tela.blit(
            dica,
            (LARGURA // 2 - dica.get_width() // 2, 420)
        )

    pygame.display.flip()

if cap is not None:
    cap.release()

pygame.quit()
