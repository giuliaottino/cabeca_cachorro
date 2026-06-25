# Implementação da tradução runtime do Tsiino

Este pacote troca a infra antiga de tradução por dois arquivos JS:

- `js/translate.js`: dicionário PT -> EN
- `js/language.js`: runtime/switcher de idioma

Também inclui:

- `_includes/language-router.html`: carrega os scripts em páginas da raiz e subpastas
- `_quarto.yml`: configuração Quarto sugerida, sem páginas `en/` e sem `css/language-toggle.css`

## Instalação rápida

Na raiz do projeto:

```bash
unzip tsiino_i18n_runtime.zip -d .
./tsiino_i18n_runtime/install_tsiino_i18n.sh
```

Depois revise o site localmente e commite:

```bash
git add -A
git commit -m "Implementa tradução runtime PT-EN do site"
git push origin "$(git branch --show-current)"
```

## Instalação manual

```bash
mkdir -p js _includes
cp tsiino_i18n_runtime/js/translate.js js/translate.js
cp tsiino_i18n_runtime/js/language.js js/language.js
cp tsiino_i18n_runtime/_includes/language-router.html _includes/language-router.html
cp tsiino_i18n_runtime/_quarto.yml _quarto.yml
rm -rf en docs/en
rm -f css/language-toggle.css
rm -f js/translations.js js/translation.js js/language-toggle.js js/lang-toggle.js js/i18n.js
node --check js/translate.js
node --check js/language.js
quarto render
git status --short
git add -A
git commit -m "Implementa tradução runtime PT-EN do site"
git push origin "$(git branch --show-current)"
```
