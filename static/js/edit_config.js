document.addEventListener('DOMContentLoaded', () => {
    const configForm = document.getElementById('config-form');
    const serverIpInput = document.getElementById('server_ip');
    const serverPortInput = document.getElementById('server_port');
    const currencyInput = document.getElementById('currency');
    const refreshIntervalSelect = document.getElementById('refresh_interval_minutes');
    const refreshIntervalCustomInput = document.getElementById('refresh_interval_minutes_custom');
    const urlFiltersContainer = document.getElementById('url-filters-container');
    const addUrlFilterBtn = document.getElementById('add-url-filter-btn');
    const loadingMessage = document.getElementById('loading-message');
    const errorMessageGlobal = document.getElementById('error-message-global');
    const successMessageGlobal = document.getElementById('success-message-global');

    let currentConfig = {};

    function displayMessage(element, message, isError = true) {
        element.textContent = message;
        element.style.display = 'block';
        element.className = isError ? 'error-message' : 'success-message';
        setTimeout(() => {
            element.style.display = 'none';
            element.textContent = '';
        }, 5000);
    }

    async function fetchConfig() {
        loadingMessage.style.display = 'block';
        errorMessageGlobal.style.display = 'none';
        successMessageGlobal.style.display = 'none';
        try {
            const response = await fetch('/api/config');
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to fetch configuration. Server returned an error.' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }
            currentConfig = await response.json();
            populateForm(currentConfig);
        } catch (error) {
            console.error('Error fetching config:', error);
            displayMessage(errorMessageGlobal, `Error loading configuration: ${error.message}`);
        } finally {
            loadingMessage.style.display = 'none';
        }
    }

    function populateForm(config) {
        serverIpInput.value = config.server_ip || '0.0.0.0';
        serverPortInput.value = config.server_port || 5000;
        currencyInput.value = config.currency || '$';

        const refreshValue = config.refresh_interval_minutes || 15;
        const standardRefreshOptions = Array.from(refreshIntervalSelect.options).map(opt => opt.value);
        if (standardRefreshOptions.includes(String(refreshValue))) {
            refreshIntervalSelect.value = String(refreshValue);
            refreshIntervalCustomInput.style.display = 'none';
        } else {
            refreshIntervalSelect.value = 'custom';
            refreshIntervalCustomInput.value = refreshValue;
            refreshIntervalCustomInput.style.display = 'block';
        }

        urlFiltersContainer.innerHTML = ''; // Clear existing filters
        if (config.url_filters && typeof config.url_filters === 'object') {
            Object.entries(config.url_filters).forEach(([url, filters]) => {
                addUrlFilterBlock(url, filters);
            });
        }
    }

    refreshIntervalSelect.addEventListener('change', () => {
        if (refreshIntervalSelect.value === 'custom') {
            refreshIntervalCustomInput.style.display = 'block';
            refreshIntervalCustomInput.focus();
        } else {
            refreshIntervalCustomInput.style.display = 'none';
        }
    });

    function createKeywordInput(keywordValue = '', levelIndex, filterIndex, keywordIndex) {
        const keywordInput = document.createElement('input');
        keywordInput.type = 'text';
        keywordInput.className = 'keyword-input';
        keywordInput.value = keywordValue;
        keywordInput.placeholder = 'Keyword';
        keywordInput.dataset.levelIndex = levelIndex;
        keywordInput.dataset.filterIndex = filterIndex;
        keywordInput.dataset.keywordIndex = keywordIndex;
        return keywordInput;
    }

    function createRemoveButton(onClick) {
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'remove-btn';
        removeBtn.textContent = 'Remove';
        removeBtn.addEventListener('click', onClick);
        return removeBtn;
    }

    function createAddButton(text, onClick) {
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'add-btn';
        addBtn.textContent = text;
        addBtn.addEventListener('click', onClick);
        return addBtn;
    }

    function addFilterLevelBlock(filterBlock, levelName = '', keywords = [], filterIndex, levelIndex = null) {
        const currentLevelCount = filterBlock.querySelectorAll('.filter-level-block').length;
        const actualLevelIndex = levelIndex === null ? currentLevelCount + 1 : levelIndex;

        const levelDiv = document.createElement('div');
        levelDiv.className = 'filter-level-block';
        levelDiv.dataset.filterIndex = filterIndex;
        levelDiv.dataset.levelIndex = actualLevelIndex; // Store the intended level number

        const levelLabel = document.createElement('label');
        levelLabel.textContent = `Level ${actualLevelIndex} Keywords:`;
        levelDiv.appendChild(levelLabel);

        const keywordsContainer = document.createElement('div');
        keywordsContainer.className = 'keywords-container';
        levelDiv.appendChild(keywordsContainer);

        if (keywords.length === 0) { // Add one empty keyword input if new level
            keywords.push('');
        }
        keywords.forEach((keyword, keywordIndex) => {
            const keywordWrapper = document.createElement('div');
            keywordWrapper.className = 'keyword-wrapper';
            const keywordInput = createKeywordInput(keyword, actualLevelIndex, filterIndex, keywordIndex);
            keywordWrapper.appendChild(keywordInput);
            if (keywords.length > 1 || keywordIndex > 0) { // Show remove button if more than one or not the first
                 keywordWrapper.appendChild(createRemoveButton(() => {
                    keywordWrapper.remove();
                    // Renumber levels if a level is removed (cascading) is handled by re-reading the form
                }));
            }
            keywordsContainer.appendChild(keywordWrapper);
        });


        levelDiv.appendChild(createAddButton('Add Keyword to Level ' + actualLevelIndex, () => {
            const keywordWrapper = document.createElement('div');
            keywordWrapper.className = 'keyword-wrapper';
            const newKeywordIndex = keywordsContainer.querySelectorAll('.keyword-input').length;
            const newKeywordInput = createKeywordInput('', actualLevelIndex, filterIndex, newKeywordIndex);
            keywordWrapper.appendChild(newKeywordInput);
            keywordWrapper.appendChild(createRemoveButton(() => keywordWrapper.remove()));
            keywordsContainer.appendChild(keywordWrapper);
            newKeywordInput.focus();
        }));

        levelDiv.appendChild(createRemoveButton(() => {
            levelDiv.remove();
            // After removing a level, re-number the subsequent levels for this URL filter
            const parentFilterBlock = filterBlock.querySelector('.filter-levels-container');
            const remainingLevels = parentFilterBlock.querySelectorAll('.filter-level-block');
            remainingLevels.forEach((remLevel, idx) => {
                const newLevelNum = idx + 1;
                remLevel.dataset.levelIndex = newLevelNum;
                remLevel.querySelector('label').textContent = `Level ${newLevelNum} Keywords:`;
                remLevel.querySelectorAll('.keyword-input').forEach(kwInput => kwInput.dataset.levelIndex = newLevelNum);
                const addKwBtn = remLevel.querySelector('.add-btn');
                if(addKwBtn) addKwBtn.textContent = 'Add Keyword to Level ' + newLevelNum;
            });
        }));
        filterBlock.querySelector('.filter-levels-container').appendChild(levelDiv);
    }


    function addUrlFilterBlock(url = '', filters = {}) {
        const filterIndex = urlFiltersContainer.children.length;
        const block = document.createElement('div');
        block.className = 'url-filter-block';
        block.dataset.filterIndex = filterIndex;

        const urlLabel = document.createElement('label');
        urlLabel.textContent = 'Filter URL:';
        const urlInput = document.createElement('input');
        urlInput.type = 'text';
        urlInput.className = 'url-input';
        urlInput.value = url;
        urlInput.placeholder = 'https://www.facebook.com/marketplace/...';
        urlInput.required = true;
        block.appendChild(urlLabel);
        block.appendChild(urlInput);

        const filterLevelsContainer = document.createElement('div');
        filterLevelsContainer.className = 'filter-levels-container';
        block.appendChild(filterLevelsContainer);


        // Sort filter levels (level1, level2, etc.) before adding
        const sortedLevels = Object.entries(filters)
            .filter(([key]) => key.startsWith('level') && !isNaN(parseInt(key.substring(5))))
            .sort(([keyA], [keyB]) => parseInt(keyA.substring(5)) - parseInt(keyB.substring(5)));

        if (sortedLevels.length === 0) { // If no levels, add a default Level 1
            addFilterLevelBlock(block, 'level1', [], filterIndex, 1);
        } else {
            sortedLevels.forEach(([levelName, keywords], index) => {
                const levelNum = parseInt(levelName.substring(5));
                addFilterLevelBlock(block, levelName, keywords, filterIndex, levelNum);
            });
        }


        block.appendChild(createAddButton('Add Filter Level', () => {
            const existingLevels = block.querySelectorAll('.filter-level-block').length;
            addFilterLevelBlock(block, `level${existingLevels + 1}`, [], filterIndex, existingLevels + 1);
        }));

        block.appendChild(createRemoveButton(() => {
            block.remove();
            // Re-index subsequent filter blocks if needed (though not strictly necessary for data collection)
            Array.from(urlFiltersContainer.children).forEach((child, idx) => {
                child.dataset.filterIndex = idx;
                // Update indices within the child if necessary
            });
        }));

        urlFiltersContainer.appendChild(block);
    }

    addUrlFilterBtn.addEventListener('click', () => addUrlFilterBlock());

    configForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        errorMessageGlobal.style.display = 'none';
        successMessageGlobal.style.display = 'none';

        const formData = {
            server_ip: serverIpInput.value.trim(),
            server_port: parseInt(serverPortInput.value, 10),
            currency: currencyInput.value.trim(),
            refresh_interval_minutes: refreshIntervalSelect.value === 'custom' ?
                                      parseInt(refreshIntervalCustomInput.value, 10) :
                                      parseInt(refreshIntervalSelect.value, 10),
            url_filters: {}
        };

        // Basic client-side validation
        if (!formData.server_ip) {
            displayMessage(errorMessageGlobal, "Server IP cannot be empty.");
            return;
        }
        if (isNaN(formData.server_port) || formData.server_port <= 0 || formData.server_port > 65535) {
            displayMessage(errorMessageGlobal, "Server Port must be a number between 1 and 65535.");
            return;
        }
        if (!formData.currency) {
            displayMessage(errorMessageGlobal, "Currency symbol cannot be empty.");
            return;
        }
        if (isNaN(formData.refresh_interval_minutes) || formData.refresh_interval_minutes <= 0) {
            displayMessage(errorMessageGlobal, "Refresh interval must be a positive number.");
            return;
        }


        const urlFilterBlocks = urlFiltersContainer.querySelectorAll('.url-filter-block');
        let formIsValid = true;
        urlFilterBlocks.forEach(block => {
            const urlInput = block.querySelector('.url-input');
            const url = urlInput.value.trim();
            if (!url) {
                displayMessage(errorMessageGlobal, "Filter URL cannot be empty for a filter block.");
                urlInput.style.borderColor = 'red';
                formIsValid = false;
                return; // exit forEach iteration for this block
            }
            urlInput.style.borderColor = ''; // reset border

            try {
                new URL(url); // Validate URL format
                if (!url.startsWith("https://www.facebook.com/marketplace/")) {
                     // Soft warning, still allow, but good to note
                    console.warn(`URL "${url}" does not look like a standard Facebook Marketplace URL.`);
                }
            } catch (e) {
                displayMessage(errorMessageGlobal, `Invalid URL format: ${url}`);
                urlInput.style.borderColor = 'red';
                formIsValid = false;
                return;
            }


            formData.url_filters[url] = {};
            const levelBlocks = block.querySelectorAll('.filter-level-block');
            levelBlocks.forEach((levelBlock) => {
                const levelIndex = levelBlock.dataset.levelIndex; // Use the stored level index
                const levelName = `level${levelIndex}`;
                formData.url_filters[url][levelName] = [];
                const keywordInputs = levelBlock.querySelectorAll('.keyword-input');
                let levelHasKeywords = false;
                keywordInputs.forEach(kwInput => {
                    const keyword = kwInput.value.trim();
                    if (keyword) {
                        formData.url_filters[url][levelName].push(keyword);
                        levelHasKeywords = true;
                    }
                });
                if (!levelHasKeywords && Object.keys(formData.url_filters[url]).length > 0) {
                    // If a level has no keywords, but the URL filter itself is not empty,
                    // it might be an issue depending on backend logic.
                    // For now, we allow empty levels if the user explicitly creates them.
                    // If an entire level is empty, we can choose to not send it.
                    if(formData.url_filters[url][levelName].length === 0){
                        delete formData.url_filters[url][levelName];
                    }
                }
            });
            // If a URL filter ends up with no levels, remove it
            if (Object.keys(formData.url_filters[url]).length === 0) {
                delete formData.url_filters[url];
            }
        });

        if (!formIsValid) {
            return;
        }

        console.log('Submitting config:', JSON.stringify(formData, null, 2));

        try {
            const response = await fetch('/api/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData),
            });
            const result = await response.json();
            if (response.ok) {
                displayMessage(successMessageGlobal, result.message || 'Configuration saved successfully!', false);
                currentConfig = formData; // Update local currentConfig on successful save
                // Optionally re-fetch or just re-populate to ensure UI consistency if backend modifies data
                populateForm(currentConfig); // Re-populate to clean up UI (e.g. re-number levels if some were deleted)
            } else {
                displayMessage(errorMessageGlobal, result.detail || 'Failed to save configuration.');
            }
        } catch (error) {
            console.error('Error saving config:', error);
            displayMessage(errorMessageGlobal, `Error saving configuration: ${error.message}`);
        }
    });

    // Initial fetch of config
    fetchConfig();
});