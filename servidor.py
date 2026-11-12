import asyncio
import json
import os
import random
import string
import websockets

salas = {}  # { "ABCD": {"host": ws, "guest": ws} }

def gerar_codigo():
    while True:
        cod = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        if cod not in salas:
            return cod

async def handler(websocket):
    codigo_atual = None
    papel = None
    try:
        async for message in websocket:
            # Se for bytes binários (pedaços da música), repassa direto pro oponente
            if isinstance(message, bytes):
                if codigo_atual in salas:
                    destino = salas[codigo_atual]["guest"] if papel == "host" else salas[codigo_atual]["host"]
                    if destino:
                        await destino.send(message)
                continue

            dados = json.loads(message)
            tipo = dados.get("tipo")

            if tipo == "CRIAR_SALA":
                codigo_atual = gerar_codigo()
                papel = "host"
                salas[codigo_atual] = {"host": websocket, "guest": None}
                await websocket.send(json.dumps({"tipo": "SALA_CRIADA", "codigo": codigo_atual}))

            elif tipo == "ENTRAR_SALA":
                cod = dados.get("codigo", "").upper()
                if cod in salas and salas[cod]["guest"] is None:
                    codigo_atual = cod
                    papel = "guest"
                    salas[cod]["guest"] = websocket
                    await websocket.send(json.dumps({"tipo": "ENTROU_OK", "codigo": cod}))
                    await salas[cod]["host"].send(json.dumps({"tipo": "PLAYER2_ENTROU"}))
                else:
                    await websocket.send(json.dumps({"tipo": "ERRO", "msg": "Sala inválida ou cheia!"}))

            # Qualquer outro comando (CHECK_MUSICA, START, PONTOS, etc.) é repassado
            elif codigo_atual in salas:
                destino = salas[codigo_atual]["guest"] if papel == "host" else salas[codigo_atual]["host"]
                if destino:
                    await destino.send(message)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if codigo_atual in salas:
            oponente = salas[codigo_atual]["guest"] if papel == "host" else salas[codigo_atual]["host"]
            if oponente:
                try:
                    await oponente.send(json.dumps({"tipo": "OPONENTE_SAIU"}))
                except:
                    pass
            del salas[codigo_atual]

async def main():
    porta = int(os.environ.get("PORT", 8765))
    async with websockets.serve(handler, "0.0.0.0", porta, max_size=50 * 1024 * 1024):
        print(f"Servidor Relay rodando na porta {porta}...")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
