# Polymarket BTC 15m Assistant

Um assistente de trading em tempo real no terminal para os mercados de 15 minutos do Polymarket "Bitcoin Up or Down".

Ele combina:
- selecao de mercado no Polymarket + precos UP/DOWN + liquidez
- feed ao vivo do Chainlink BTC/USD via WebSocket do proprio Polymarket
- fallback para Chainlink on-chain na Polygon via HTTP/WSS RPC
- preco spot da Binance como referencia
- snapshot de analise tecnica de curto prazo (Heiken Ashi, RSI, MACD, VWAP, delta de 1/3 min)
- previsao ao vivo simples de LONG/SHORT (%) baseada no score atual de analise tecnica do assistente

## Requisitos

- Node.js 18+ ([download](https://nodejs.org/en))
- npm (ja vem com o Node)

## Como rodar no terminal

### 1) Clone o repositorio

```bash
git clone https://github.com/FrondEnt/PolymarketBTC15mAssistant.git
```

Alternativa (sem git):

- clique no botao verde `<> Code` no GitHub
- escolha `Download ZIP`
- extraia o ZIP
- abra um terminal dentro da pasta extraida do projeto

### 2) Instale as dependencias

```bash
npm install
```

### 3) (Opcional) Defina variaveis de ambiente

Voce pode rodar sem configuracao extra, porque ja existem valores padrao. Ainda assim, para um fallback mais estavel do Chainlink, e recomendado definir pelo menos um RPC da Polygon.

#### Windows PowerShell (sessao atual do terminal)

```powershell
$env:POLYGON_RPC_URL = "https://polygon-rpc.com"
$env:POLYGON_RPC_URLS = "https://polygon-rpc.com,https://rpc.ankr.com/polygon"
$env:POLYGON_WSS_URLS = "wss://polygon-bor-rpc.publicnode.com"
```

Configuracoes opcionais do Polymarket:

```powershell
$env:POLYMARKET_AUTO_SELECT_LATEST = "true"
# $env:POLYMARKET_SLUG = "btc-updown-15m-..."   # fixa um mercado especifico
```

#### Windows CMD (sessao atual do terminal)

```cmd
set POLYGON_RPC_URL=https://polygon-rpc.com
set POLYGON_RPC_URLS=https://polygon-rpc.com,https://rpc.ankr.com/polygon
set POLYGON_WSS_URLS=wss://polygon-bor-rpc.publicnode.com
```

Configuracoes opcionais do Polymarket:

```cmd
set POLYMARKET_AUTO_SELECT_LATEST=true
REM set POLYMARKET_SLUG=btc-updown-15m-...
```

Observacoes:

- essas variaveis valem apenas para a janela atual do terminal
- se quiser variaveis permanentes, configure nas variaveis de ambiente do Windows ou use o carregador de `.env` que preferir

## Configuracao

Este projeto le configuracoes a partir de variaveis de ambiente.

Voce pode defini-las no shell ou criar um arquivo `.env` e carrega-lo com o metodo que preferir.

### Polymarket

- `POLYMARKET_AUTO_SELECT_LATEST` (padrao: `true`)
  - quando estiver como `true`, escolhe automaticamente o mercado de 15 minutos mais recente
- `POLYMARKET_SERIES_ID` (padrao: `10192`)
- `POLYMARKET_SERIES_SLUG` (padrao: `btc-up-or-down-15m`)
- `POLYMARKET_SLUG` (opcional)
  - se for definido, o assistente vai mirar em um slug de mercado especifico
- `POLYMARKET_LIVE_WS_URL` (padrao: `wss://ws-live-data.polymarket.com`)

### Chainlink na Polygon (fallback)

- `CHAINLINK_BTC_USD_AGGREGATOR`
  - padrao: `0xc907E116054Ad103354f2D350FD2514433D57F6f`

HTTP RPC:

- `POLYGON_RPC_URL` (padrao: `https://polygon-rpc.com`)
- `POLYGON_RPC_URLS` (opcional, separado por virgulas)
  - exemplo: `https://polygon-rpc.com,https://rpc.ankr.com/polygon`

WSS RPC (opcional, mas recomendado para fallback mais em tempo real):

- `POLYGON_WSS_URL` (opcional)
- `POLYGON_WSS_URLS` (opcional, separado por virgulas)

### Suporte a proxy

O bot suporta proxies HTTP(S) tanto para requisicoes HTTP (`fetch`) quanto para conexoes WebSocket.

Variaveis suportadas (padrao de mercado):

- `HTTPS_PROXY` / `https_proxy`
- `HTTP_PROXY` / `http_proxy`
- `ALL_PROXY` / `all_proxy`

Exemplos:

PowerShell:

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:8080"
# ou
$env:ALL_PROXY = "socks5://127.0.0.1:1080"
```

CMD:

```cmd
set HTTPS_PROXY=http://127.0.0.1:8080
REM ou
set ALL_PROXY=socks5://127.0.0.1:1080
```

#### Proxy com usuario + senha

1. Pegue o host e a porta do proxy (exemplo: `1.2.3.4:8080`).
2. Adicione login e senha na URL.

- proxy HTTP/HTTPS:
  - `http://USUARIO:SENHA@HOST:PORTA`
- proxy SOCKS5:
  - `socks5://USUARIO:SENHA@HOST:PORTA`

3. Defina no terminal e rode o bot.

PowerShell:

```powershell
$env:HTTPS_PROXY = "http://USUARIO:SENHA@HOST:PORTA"
npm start
```

CMD:

```cmd
set HTTPS_PROXY=http://USUARIO:SENHA@HOST:PORTA
npm start
```

Importante: se sua senha tiver caracteres especiais como `@` ou `:`, faca URL encode.

Exemplo:

- senha: `p@ss:word`
- codificada: `p%40ss%3Aword`
- URL do proxy: `http://user:p%40ss%3Aword@1.2.3.4:8080`

## Execucao

```bash
npm start
```

### Parar

Pressione `Ctrl + C` no terminal.

### Atualizar para a versao mais recente

```bash
git pull
npm install
npm start
```

## Observacoes / Solucao de problemas

- se nao aparecerem atualizacoes do Chainlink:
  - o WebSocket do Polymarket pode estar temporariamente indisponivel; nesse caso o bot faz fallback para o preco on-chain do Chainlink via RPC da Polygon
  - garanta que pelo menos um RPC valido da Polygon esteja configurado
- se o terminal parecer estar "spamando" linhas:
  - o renderizador usa `readline.cursorTo` + `clearScreenDown` para manter a tela estavel, mas alguns terminais podem se comportar de forma diferente

## Seguranca

Isto nao e conselho financeiro. Use por sua conta e risco.

criado por @krajekis
