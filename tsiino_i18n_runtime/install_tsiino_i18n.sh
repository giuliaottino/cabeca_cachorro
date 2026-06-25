#!/usr/bin/env bash
set -euo pipefail

# Rode este script na raiz do projeto Quarto do Tsiino.
# Ele substitui a infra antiga de idioma por js/translate.js + js/language.js.

if [ ! -f "_quarto.yml" ]; then
  echo "ERRO: _quarto.yml não encontrado. Rode este script na raiz do projeto."
  exit 1
fi

if [ ! -d ".git" ]; then
  echo "AVISO: .git não encontrado nesta pasta. Continuando sem validação de repositório."
fi

echo "==> Backup do _quarto.yml atual"
cp _quarto.yml "_quarto.yml.bak.$(date +%Y%m%d%H%M%S)"

echo "==> Criando pastas necessárias"
mkdir -p js _includes

echo "==> Copiando nova infra de tradução"
cp tsiino_i18n_runtime/js/translate.js js/translate.js
cp tsiino_i18n_runtime/js/language.js js/language.js
cp tsiino_i18n_runtime/_includes/language-router.html _includes/language-router.html
cp tsiino_i18n_runtime/_quarto.yml _quarto.yml

echo "==> Removendo ecossistema antigo de páginas EN e toggle legado"
rm -rf en docs/en
rm -f css/language-toggle.css
rm -f js/translations.js js/translation.js js/language-toggle.js js/lang-toggle.js js/i18n.js

echo "==> Checando sintaxe dos JS, se node estiver instalado"
if command -v node >/dev/null 2>&1; then
  node --check js/translate.js
  node --check js/language.js
else
  echo "node não encontrado; pulando node --check."
fi

echo "==> Renderizando site, se quarto estiver instalado"
if command -v quarto >/dev/null 2>&1; then
  quarto render
else
  echo "quarto não encontrado; pulei quarto render. Rode depois manualmente."
fi

echo "==> Status do Git"
git status --short || true

echo ""
echo "Próximos comandos sugeridos:"
echo "git add -A"
echo "git commit -m \"Implementa tradução runtime PT-EN do site\""
echo "git push origin \$(git branch --show-current)"
