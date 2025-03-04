from binance.client import Client
from binance.exceptions import BinanceAPIException
import time


class BinanceClient(Client):
    def __init__(
        self,
        api_key=None,
        api_secret=None,
        requests_params=None,
        tld="com",
        base_endpoint=Client.BASE_ENDPOINT_DEFAULT,
        testnet=False,
        private_key=None,
        private_key_pass=None,
        sync=True,
        ping=True,
        verbose=False,
        sync_interval=60000,  # Intervalo de ressincronização em ms
    ):
        """
        Inicializa o cliente Binance customizado, integrando a sincronização do timestamp com o atributo `timestamp_offset`.
        """
        super().__init__(
            api_key=api_key,
            api_secret=api_secret,
            requests_params=requests_params,
            tld=tld,
            base_endpoint=base_endpoint,
            testnet=testnet,
            private_key=private_key,
            private_key_pass=private_key_pass,
        )

        # Configurações de sincronização
        self.sync = sync
        self.verbose = verbose
        self.sync_interval = sync_interval
        self.last_sync_time = 0  # Armazena o tempo da última sincronização

        if self.sync:
            self.sync_time_offset()

        # Executa o ping inicial se solicitado
        if ping:
            self.ping()

    def sync_time_offset(self, force=False):
        """
        Sincroniza o desvio de tempo (`timestamp_offset`) com base no relógio local e no servidor Binance.
        Realiza a sincronização apenas se for forçada ou se o intervalo configurado tiver passado.
        """
        current_time = int(time.time() * 1000)
        if force or (current_time - self.last_sync_time >= self.sync_interval):
            try:
                server_time = self.get_server_time()["serverTime"]
                local_time = int(time.time() * 1000)
                self.timestamp_offset = server_time - local_time
                self.last_sync_time = current_time
                if self.verbose:
                    print(f"⏰ Desvio de tempo sincronizado: {self.timestamp_offset}ms")
            except Exception as e:
                print(f"⚠️ Erro ao sincronizar o desvio de tempo: {e}")
                self.timestamp_offset = 0

    def _request(self, method, uri: str, signed: bool, force_params: bool = False, **kwargs):
        """
        Sobrescreve o método `_request` para integrar a sincronização automática do `timestamp_offset` em requisições assinadas.
        """
        if signed:
            # Atualiza o timestamp para requisições assinadas
            current_time = int(time.time() * 1000)
            if self.sync and (self.timestamp_offset is None or abs(self.timestamp_offset) > 1000):
                self.sync_time_offset(force=True)
            elif self.sync and (current_time - self.last_sync_time >= self.sync_interval):
                self.sync_time_offset()

            kwargs.setdefault("data", {})
            kwargs["data"]["timestamp"] = int(time.time() * 1000 + self.timestamp_offset)

        try:
            return super()._request(method, uri, signed, force_params, **kwargs)
        except BinanceAPIException as e:
            if e.code == -1021:  # Erro de timestamp
                print(f"⚠️ Erro de timestamp detectado: {e}. Re-sincronizando...")
                self.sync_time_offset(force=True)
                if signed:
                    kwargs["data"]["timestamp"] = int(time.time() * 1000 + self.timestamp_offset)
                return super()._request(method, uri, signed, force_params, **kwargs)
            else:
                raise e
