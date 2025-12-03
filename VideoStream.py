class VideoStream:
    def __init__(self, filename):
        self.filename = filename
        try:
            self.file = open(filename, 'rb')
        except:
            raise IOError
        self.frameNum = 0
        self.buffer = b""

    def nextFrame(self):
        """Retorna o próximo quadro JPEG completo ou `None` se acabar."""
        while True:
            # procura marcadores JPEG no buffer
            start_index = self.buffer.find(b'\xff\xd8')
            end_index = self.buffer.find(b'\xff\xd9')

            if start_index != -1 and end_index != -1 and end_index > start_index:
                # recorta quadro e atualiza buffer
                frame = self.buffer[start_index : end_index + 2]
                self.buffer = self.buffer[end_index + 2:]
                self.frameNum += 1
                return frame

            chunk = self.file.read(4096)
            if not chunk:
                return None

            self.buffer += chunk

    def frameNbr(self):
        """Número do quadro atual."""
        return self.frameNum