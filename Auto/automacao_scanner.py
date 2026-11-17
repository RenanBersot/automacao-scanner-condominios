import os
import time
import io
import warnings
import concurrent.futures
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Optional
from pypdf import PdfReader, PdfWriter

warnings.filterwarnings("ignore")

# ================= CONFIGURAÇÕES =================
API_KEY = "SUA_API_KEY_AQUI"
PASTA_SCANNER = r"C:\Users\renan.bersot\Documents\Salvos" 
PASTA_DESTINO = r"C:\Users\renan.bersot\Documents\Processados" 

# ================= SCHEMA DE RESPOSTA =================
class AnalisePagina(BaseModel):
    raciocinio: str = Field(description="Pense como um humano financeiro. Explique o seu raciocínio passo a passo: 1) Esta página tem anotação manual para ser a capa? 2) Qual é a intenção real da data (ignorando cabeçalhos de e-mail e interpretando parcelas)? 3) Qual é o valor exato a sair da conta hoje?")
    eh_novo_documento: bool = Field(description="True se a página possuir um carimbo preenchido ou anotação identificando o início. False caso contrário.")
    condominio: Optional[str] = Field(description="O número do condomínio. Null se não houver.")
    data_vencimento: Optional[str] = Field(description="Data real no formato DD.MM.AA. Null se não houver.")
    valor: Optional[str] = Field(description="Valor real da cobrança/parcela. Null se não houver.")

client = genai.Client(api_key=API_KEY)

def analisar_pagina(page_bytes: bytes) -> AnalisePagina:
    """Envia uma página para a IA analisar, com regras antifalhas rigorosas."""
    prompt = """
    Você é um assistente financeiro sênior.
    
    COMO PENSAR (Preencha o 'raciocinio' detalhadamente ANTES de extrair os dados):
    1. CRIE UMA TABELA MENTAL: Se o documento tiver uma lista de datas para depósito (ex: 10/10, 10/11, 10/12...), ESCREVA a correspondência exata agora mesmo para não pular meses: Parc 01 = 10/10, Parc 02 = 10/11, Parc 03 = 10/12, Parc 04 = 10/01, Parc 05 = 10/02, Parc 06 = 10/03...
    2. A página tem anotação indicando condomínio e parcela (ex: Parc: 03/10)? Olhe para a tabela que acabou de criar e defina a data exata dessa parcela.
    
    REGRAS ANTIFALHAS DE VISÃO (GABARITO DE EXTRAÇÃO):
    - 'condominio': A sua visão erra na caligrafia humana. O condomínio '156' às vezes tem o '1' desenhado parecendo um '4'. Se você ler '456', CORRIJA IMEDIATAMENTE PARA '156'. 
    - 'data_vencimento':
        1º Para parcelamentos (Parc: XX): Use EXATAMENTE a data correspondente da tabela que você gerou.
        2º Cuidado com rabiscos: Se a anotação manual tiver um número riscado e outro ao lado, pegue a data limpa (ex: ignore o 08 e pegue o 10).
        -> Retorne SEMPRE no formato DD.MM.AA (converta o ano para 2026 ou 2027 seguindo a ordem lógica dos meses).
    - 'valor': Se o texto fala que a parcela é '599,00', o valor é EXATAMENTE '599,00'. NÃO confunda a fonte e não invente números como '595,00'.
    """
    
    max_tentativas = 3 
    
    for tentativa in range(max_tentativas):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[
                    types.Part.from_bytes(data=page_bytes, mime_type="application/pdf"),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AnalisePagina,
                    temperature=0.1
                ),
            )
            return AnalisePagina.model_validate_json(response.text)
            
        except Exception as e:
            if tentativa < max_tentativas - 1:
                time.sleep(2) 
            else:""
            raise e
            
def salvar_documento_fatiado(pdf_writer: PdfWriter, dados: AnalisePagina):
    """Salva o PDF fatiado com o nome correto na pasta de destino."""
    cond = dados.condominio if dados.condominio else "SEM_COND"
    venc = dados.data_vencimento if dados.data_vencimento else "SEM_DATA"
    val = dados.valor if dados.valor else "0,00"

    nome_base = f"({cond}) {venc} - R$ {val}"
    nome_base = "".join(c for c in nome_base if c not in r'\/:*?"<>|')
    
    caminho_final = Path(PASTA_DESTINO) / f"{nome_base}.pdf"
    contador = 1
    while caminho_final.exists():
        caminho_final = Path(PASTA_DESTINO) / f"{nome_base} ({contador}).pdf"
        contador += 1

    with open(caminho_final, "wb") as f_out:
        pdf_writer.write(f_out)
    
    print(f"[✓] Salvo: {caminho_final.name}")

def processar_lote(caminho_arquivo: str):
    """Lê o PDF e processa todas as páginas em paralelo (Multithreading)."""
    caminho = Path(caminho_arquivo)
    if caminho.suffix.lower() != ".pdf" or caminho.name.startswith("~"):
        return

    print(f"\n[+] Novo lote detetado: {caminho.name}")
    time.sleep(4) # Espera a impressora terminar de criar o PDF original

    try:
        leitor_pdf = PdfReader(str(caminho))
        total_paginas = len(leitor_pdf.pages)
        print(f"[*] A preparar {total_paginas} página(s) para envio simultâneo...")

        # 1. Converte todas as páginas para bytes antes de enviar
        paginas_preparadas = []
        for pagina in leitor_pdf.pages:
            temp_writer = PdfWriter()
            temp_writer.add_page(pagina)
            pdf_bytes_io = io.BytesIO()
            temp_writer.write(pdf_bytes_io)
            paginas_preparadas.append((pagina, pdf_bytes_io.getvalue()))

        # 2. Envia todas as páginas à IA de uma só vez (15 processos ao mesmo tempo)
        print("[*] A analisar o lote inteiro na nuvem...")
        bytes_list = [pb[1] for pb in paginas_preparadas]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            # O executor.map garante que as respostas voltam na ordem original exata das páginas
            resultados_ia = list(executor.map(analisar_pagina, bytes_list))

        # 3. Lógica de Agrupamento (O Agrafador)
        print("[*] A montar os PDFs finais...")
        escritor_atual = None
        dados_atuais = None

        for i, (pagina, _) in enumerate(paginas_preparadas):
            resultado = resultados_ia[i]

            if resultado.eh_novo_documento:
                if escritor_atual is not None and dados_atuais is not None:
                    salvar_documento_fatiado(escritor_atual, dados_atuais)

                escritor_atual = PdfWriter()
                escritor_atual.add_page(pagina)
                dados_atuais = resultado
            else:
                if escritor_atual is not None:
                    escritor_atual.add_page(pagina)
                else:
                    escritor_atual = PdfWriter()
                    escritor_atual.add_page(pagina)
                    dados_atuais = resultado

        if escritor_atual is not None and dados_atuais is not None:
            salvar_documento_fatiado(escritor_atual, dados_atuais)
        
        print(f"[*] Fatiamento concluído!")

    except Exception as e:
        print(f"[!] Erro ao processar: {e}")

class MonitorScanner(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            processar_lote(event.src_path)

if __name__ == "__main__":
    os.makedirs(PASTA_SCANNER, exist_ok=True)
    os.makedirs(PASTA_DESTINO, exist_ok=True)

    event_handler = MonitorScanner()
    observer = Observer()
    observer.schedule(event_handler, path=PASTA_SCANNER, recursive=False)
    observer.start()

    print(f"[*] A monitorizar: {PASTA_SCANNER} (Multithreading Ativado)")
    print("[*] Pressiona Ctrl+C para encerrar.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()