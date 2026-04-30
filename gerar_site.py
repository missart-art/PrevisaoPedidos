import os, ast, json

def pegar_requisitos(pasta):
    libs = set()
    std_lib = {"os", "sys", "json", "sqlite3", "datetime", "math", "re", "io", "base64"}
    for f in os.listdir(pasta):
        if f.endswith(".py"):
            with open(os.path.join(pasta, f), "r", encoding="utf-8") as file:
                tree = ast.parse(file.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            lib = n.name.split('.')[0]
                            if lib not in std_lib: libs.add(lib)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            lib = node.module.split('.')[0]
                            if lib not in std_lib: libs.add(lib)
    return list(libs)

def gerar_manual(pasta_origem):
    # 1. Pega os códigos de TODOS os arquivos .py
    arquivos_dict = {}
    for f in os.listdir(pasta_origem):
        if f.endswith(".py"):
            with open(os.path.join(pasta_origem, f), "r", encoding="utf-8") as file:
                arquivos_dict[f] = file.read()

    # 2. Pega todas as bibliotecas de todos os arquivos
    requisitos = pegar_requisitos(pasta_origem)
    
    # 3. Monta o HTML (o motor vai carregar o app.py como principal)
    html = f"""
    <script src="https://cdn.jsdelivr.net/npm/@stlite/mountable@0.39.0/build/stlite.js"></script>
    <script>
      stlite.mount({{
        requirements: {json.dumps(requisitos)},
        files: {json.dumps(arquivos_dict)},
        entrypoint: "app.py"
      }}, document.getElementById("root"));
    </script>
    """
    with open("index.html", "w", encoding="utf-8") as f: f.write(html)
    print(f"✅ Gerado! Bibliotecas detectadas: {requisitos}")

gerar_manual(".") # Roda na pasta atual