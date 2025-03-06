# TraderBot
### Robô de Negociação Automatizada para Binance

TraderBot é um robô de negociação automatizada desenvolvido em Python, projetado para interagir com a API da Binance. Ele permite que você automatize suas operações de compra e venda de criptomoedas, implementando estratégias de negociação personalizadas. Este projeto foi criado com o objetivo principal de aprendizado e para auxiliar traders a automatizar suas estratégias e realizar backtests eficazes.

## Funcionalidades

*   **Negociação Automatizada:** Execute ordens de compra e venda automaticamente com base em regras predefinidas.
*   **Estratégias Personalizadas:** Implemente e teste suas próprias estratégias de negociação.
*   **Backtesting:** Simule o desempenho de suas estratégias usando dados históricos da Binance.
*   **Integração com a API da Binance:** Conecte-se à sua conta Binance através da API para negociação em tempo real.

## Pré-requisitos

*   Python 3.6 ou superior instalado.
*   Conta na Binance com chaves de API habilitadas (crie em [Binance](https://www.binance.com/)).

## Instalação

1.  **Clone o repositório:**

    ```bash
    git clone <URL_DO_SEU_REPOSITÓRIO>
    cd TraderBot
    ```

2.  **Instale as dependências:**

    Abra o terminal (geralmente com `Ctrl+J` no VSCode) e execute o seguinte comando:

    ```bash
    pip install pandas python-binance python-dotenv
    ```

## Configuração

1.  **Chaves da API Binance:**

    *   Crie um arquivo chamado `.env` na raiz do projeto.
    *   Adicione suas chaves da API Binance ao arquivo `.env` no seguinte formato:

        ```python
        BINANCE_API_KEY="SUA_API_KEY"
        BINANCE_SECRET_KEY="SUA_SECRET_KEY"
        ```

        **IMPORTANTE:** Certifique-se de colocar as chaves entre aspas duplas.  Nunca compartilhe suas chaves secretas com ninguém.
        
        **AVISO:**  Armazenar chaves de API em arquivos `.env` é prático para desenvolvimento local, mas considere alternativas mais seguras (como variáveis de ambiente do sistema) para ambientes de produção.

2.  **Configuração do Interpretador Python no VSCode (Opcional):**

    Se você estiver usando o VSCode, siga estas etapas para garantir que o interpretador correto seja selecionado:

    *   Pressione `Ctrl + Shift + P` para abrir a paleta de comandos.
    *   Digite "Python: Selecionar Interpretador" e pressione Enter.
    *   Escolha o interpretador Python correto (geralmente sua instalação base ou um ambiente Conda).
    *   (Opcional) Se tiver problemas, reinicie o terminal integrado do VSCode clicando no ícone da lixeira e abrindo-o novamente.

3.  **Configuração do Bot:**

    A lógica principal de configuração do bot está localizada no arquivo `src/main.py`.  Edite este arquivo para personalizar as configurações da sua estratégia de negociação, como:

    *   Pares de criptomoedas para negociar (ex: `BTCUSDT`, `ETHBTC`)
    *   Valor/quantidade a ser negociado por ordem.
    *   Indicadores técnicos e regras de entrada/saída.

## Execução

1.  **Rodar o Bot:**

    Para iniciar o bot de negociação, execute o seguinte comando no terminal:

    ```bash
    python src/main.py
    ```

2.  **Rodar os Backtests:**

    Para executar simulações de backtesting com seus dados históricos, execute o seguinte comando:

    ```bash
    python src/backtests.py
    ```

## Termos de Uso e Isenção de Responsabilidade

Este robô/código é fornecido "como está" e para fins educacionais. O uso é de sua total responsabilidade. Os desenvolvedores não se responsabilizam por quaisquer perdas financeiras ou outros danos decorrentes do uso deste código.

**Negocie com responsabilidade e esteja ciente dos riscos envolvidos na negociação de criptomoedas.**

Ao usar este código, você concorda com os termos da licença [GNU Affero General Public License](./LICENSE).

## Autores

*   Desenvolvido inicialmente por Gabriel Freitas.
    *   [YouTube](https://www.youtube.com/@DescolaDev)
    *   [Instagram](https://instagram.com/gabrielfreitas.dev)
    *   [Discord](https://discord.gg/PpmB3DwSSX)
*   Fork realizado em 05/02/2025 por Adriano Tavares.

## Contribuição

Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou enviar pull requests para melhorar o TraderBot.
