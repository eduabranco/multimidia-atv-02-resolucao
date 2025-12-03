import sys
from tkinter import Tk
from Client import Client

if __name__ == "__main__":
    try:
        serverAddr = sys.argv[1]
        serverPort = sys.argv[2]
        rtpPort = sys.argv[3]
        fileName = sys.argv[4]    
    except:
        print("[Uso: ClientLauncher.py Server_IP Server_Port RTP_Port Video_File]")
        print("Exemplo: python3 ClientLauncher.py 127.0.0.1 12000 5008 movie.Mjpeg")
        sys.exit(0)
    
    root = Tk()

    # instancia o cliente
    app = Client(root, serverAddr, serverPort, rtpPort, fileName)
    app.master.title("RTP Client")    
    root.mainloop()