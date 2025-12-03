import sys, socket
from ServerWorker import ServerWorker

class Server:
    def main(self):
        try:
            SERVER_PORT = int(sys.argv[1])
        except:
            print("[Uso: Server.py Porta_Servidor]")
            print("Exemplo: python3 Server.py 12000")
            return

        rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        rtspSocket.bind(("", SERVER_PORT))
        rtspSocket.listen(5)

        print(f"Servidor RTSP ouvindo na porta {SERVER_PORT}...")

        # aceita conexões e cria um worker por cliente
        while True:
            clientInfo = {}
            clientInfo['rtspSocket'] = rtspSocket.accept()
            ServerWorker(clientInfo).run()

if __name__ == "__main__":
    (Server()).main()