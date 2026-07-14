/* TSIINO_FORMDATA_FILE_FIX_V18
   Corrige chamadas FormData.append('file', valorNaoBlob, filename) no mapeador.
   O navegador exige que o 2o argumento seja Blob/File quando o 3o argumento existe.
*/
(function () {
  if (window.__TSIINO_FORMDATA_FILE_FIX_V18__) return;
  window.__TSIINO_FORMDATA_FILE_FIX_V18__ = true;

  const nativeAppend = FormData.prototype.append;

  function selectedSpreadsheetFile() {
    const input = document.getElementById('spreadsheet-file');
    if (input && input.files && input.files[0] instanceof Blob) return input.files[0];
    return null;
  }

  FormData.prototype.append = function tsiinoSafeAppend(name, value, filename) {
    const fieldName = String(name || '');
    const hasFilename = arguments.length >= 3;
    const isBlob = value instanceof Blob;

    if (hasFilename && !isBlob) {
      if (fieldName === 'file') {
        const file = selectedSpreadsheetFile();
        if (file) {
          return nativeAppend.call(this, name, file, file.name || filename || 'planilha.xlsx');
        }
      }
      // Evita TypeError: Argument 2 does not implement interface Blob.
      return nativeAppend.call(this, name, value == null ? '' : String(value));
    }

    return nativeAppend.apply(this, arguments);
  };

  window.TsiinoFormDataFileFixV18 = {
    ready: true,
    selectedSpreadsheetFile,
  };
})();
