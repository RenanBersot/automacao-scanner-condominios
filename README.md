# Automação de Triagem de PDFs com IA 📄🤖

Script em Python desenvolvido para automatizar a triagem, separação e renomeação de documentos físicos digitalizados em lote (boletos, notas fiscais e recibos). 

## 🚀 Funcionalidades
- **Monitoramento Automático:** Utiliza a biblioteca `watchdog` para vigiar a pasta de saída do scanner físico.
- **Processamento Paralelo:** Aplica `ThreadPoolExecutor` (Multithreading) para enviar dezenas de páginas simultaneamente para a API da IA.
- **Visão Computacional e OCR:** A IA identifica a caligrafia humana (carimbos de condomínios e datas manuscritas) para determinar onde começa e termina cada cobrança, independentemente da ordem das páginas ou anexos (NFS-e/DANFE).
- **Renomeação Inteligente:** Fatia o PDF "bolo" original e salva arquivos individuais formatados como `(Condomínio) Data - R$ Valor.pdf`.

## 🛠️ Tecnologias Utilizadas
- Python 3
- Google Gemini API (gemini-3.8-flash)
- PyPDF (Fatiamento de PDFs)
- Watchdog (Monitoramento de diretórios)
- Concurrent.futures (Multithreading)
