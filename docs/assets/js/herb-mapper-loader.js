/* TSIINO_MAPPER_OPEN_ALIAS_V10 */
(function () {
  function selectedFile() {
    const input = document.getElementById('spreadsheet-file');
    return input && input.files && input.files[0] ? input.files[0] : null;
  }

  function isPreview(value) {
    return value && typeof value === 'object' && !(value instanceof File) && (
      Array.isArray(value.source_columns) ||
      Array.isArray(value.sourceColumns) ||
      Array.isArray(value.columns) ||
      Array.isArray(value.headers) ||
      value.mapping ||
      value.suggested_mapping ||
      value.detected_standard === false
    );
  }

  function installMapperOpenAlias() {
    const integration = window.TsiinoConverterIntegration || window.TsiinoConverter;
    if (!integration || typeof integration !== 'object') {
      window.TsiinoMapperCompatReady = false;
      return false;
    }

    window.TsiinoConverterIntegration = integration;
    window.TsiinoConverter = Object.assign(window.TsiinoConverter || {}, integration);

    if (typeof integration.open !== 'function') {
      integration.open = async function (previewOrFile, maybeFile) {
        const preview = isPreview(previewOrFile) ? previewOrFile : null;
        const file = maybeFile instanceof File
          ? maybeFile
          : (previewOrFile instanceof File ? previewOrFile : selectedFile());

        if (typeof integration.openFromPreview === 'function' && preview) {
          return await integration.openFromPreview(preview);
        }
        if (typeof integration.openAfterValidationFailure === 'function') {
          return await integration.openAfterValidationFailure(preview || file);
        }
        if (typeof integration.showFromFile === 'function') {
          return await integration.showFromFile(file, preview);
        }
        if (typeof integration.openMapper === 'function') {
          return await integration.openMapper(file, preview);
        }
        throw new Error('Nenhum método de abertura do mapeador está disponível.');
      };
    }

    if (typeof integration.openAfterValidationFailure !== 'function') {
      integration.openAfterValidationFailure = function (previewOrFile) {
        return integration.open(previewOrFile, selectedFile());
      };
    }

    if (typeof window.TsiinoConverter.showFromFile !== 'function') {
      window.TsiinoConverter.showFromFile = function (file, preview) {
        return integration.open(preview || file, file);
      };
    }
    if (typeof window.TsiinoConverter.openAfterValidationFailure !== 'function') {
      window.TsiinoConverter.openAfterValidationFailure = function (previewOrFile) {
        return integration.openAfterValidationFailure(previewOrFile);
      };
    }

    window.TsiinoMapperCompatReady = typeof integration.open === 'function';
    console.info('[Tsiino] Mapper compat v10:', {
      integration: typeof window.TsiinoConverterIntegration,
      open: typeof window.TsiinoConverterIntegration.open,
      openAfterValidationFailure: typeof window.TsiinoConverterIntegration.openAfterValidationFailure,
      showFromFile: typeof window.TsiinoConverter.showFromFile
    });
    return window.TsiinoMapperCompatReady;
  }

  installMapperOpenAlias();
  document.addEventListener('DOMContentLoaded', installMapperOpenAlias);
  window.addEventListener('load', installMapperOpenAlias);
  window.TsiinoInstallMapperOpenAlias = installMapperOpenAlias;
})();
