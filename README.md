# Ferramentas de Produção de Vídeo

Duas ferramentas para o pipeline de criação de vídeos de aula:

| Ferramenta | Descrição |
|---|---|
| **video-processor** | Interface gráfica para processar e enviar vídeos (Java) |
| **vizsh** | Visualizador de cenas para scripts `.sh` de geração FFmpeg (Python) |

## Instalação (tudo de uma vez)

```bash
git clone https://github.com/RickMitre/video-processor.git
cd video-processor
bash install.sh
```

Isso instala ambas as ferramentas. Para instalar só uma:

```bash
bash video-processor/install.sh   # só o video-processor
bash vizsh/install.sh             # só o vizsh
```

---

## video-processor

## Requisitos

- Java 21 ou superior
- [rclone](https://rclone.org/downloads/) configurado com acesso ao Google Drive

## Instalação

1. Baixe este repositório:
   ```
   git clone https://github.com/RickMitre/video-processor.git
   ```

   Ou baixe o ZIP direto: https://github.com/RickMitre/video-processor/archive/refs/heads/master.zip

2. Entre na pasta:
   ```
   cd video-processor
   ```

3. Execute o instalador:
   ```
   bash install.sh
   ```

4. Feche e abra o terminal.

## Como usar

Para abrir a interface gráfica:
```
video-processor-gui
```

---

## Tutorial

### 1. Abrindo o programa

Execute `video-processor-gui` no terminal. A janela do programa vai abrir.

---

### 2. Preenchendo os campos

**Diretório de Vídeos**
Caminho da pasta raiz onde os vídeos ficam salvos.
Exemplo: `/home/me/videos/processamento`

**Matéria**
Nome da matéria em minúsculas. Exemplos: `ciencias`, `portugues`, `matematica`, `historia`, `geografia`, `biblia`

**Ano**
Ano escolar. Exemplo: `2`

**Semana**
Número da semana (ou intervalo) a processar:
- `1` — só a semana 1
- `2-5` — semanas de 2 a 5
- `all` — todas as semanas

**Bimestres**
Marque os bimestres que deseja processar (1, 2, 3 ou 4).

**Output Files**
Arquivos gerados pelo script. Normalmente não precisa alterar.

---

### 3. Escolhendo as funções

Marque o que deseja fazer:

- **Download** — baixa o script da aula do servidor
- **Process** — executa o script e gera os vídeos
- **Upload** — envia os vídeos para o Google Drive

**Uso mais comum:** marcar Download + Process + Upload para processar e enviar tudo de uma vez.

---

### 4. Executando

Clique em **Executar**. O log na parte inferior mostra o progresso em tempo real.

Ao terminar, aparece um relatório com o resultado de cada semana processada.

---

### 5. Exemplos de uso

**Processar e enviar a semana 3 de Ciências, ano 2:**
- Matéria: `ciencias`
- Ano: `2`
- Semana: `3`
- Bimestre: marcar `1`
- Funções: Download + Process + Upload

**Processar várias semanas de uma vez:**
- Semana: `1-8`
- Bimestre: marcar `1`
- Funções: Download + Process + Upload

---

### 6. Atualização

Para atualizar para uma versão nova:
```bash
git pull
bash install.sh
```

---

## vizsh

Visualizador de cenas para scripts `.sh` de geração de vídeo com FFmpeg.

```bash
cd pasta-do-video
vizsh                     # auto-detecta o .sh no diretório
vizsh caminho/video.sh   # ou passe o caminho explícito
```

Abre em `http://localhost:9000` com preview das cenas, texto posicionado, imagens overlay e live-reload quando o `.sh` é editado.

### Requisitos vizsh
- Python 3.10+
- ffmpeg
