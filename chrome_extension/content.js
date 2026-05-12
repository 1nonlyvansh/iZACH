let ws = null;

// Semantic aliases for common field types that use different words
const SEMANTIC_ALIASES = {
    'phone':   ['mobile', 'cell', 'contact', 'tel', 'mob', 'phone', 'number'],
    'mobile':  ['phone', 'cell', 'contact', 'tel', 'mob', 'number'],
    'contact': ['phone', 'mobile', 'cell', 'tel', 'mob', 'number'],
    'tel':     ['phone', 'mobile', 'cell', 'contact', 'mob', 'number'],
    'email':   ['mail', 'e-mail', 'email'],
    'mail':    ['email', 'e-mail'],
    'address': ['addr', 'street', 'location', 'residence'],
    'addr':    ['address', 'street', 'location'],
    'father':  ['paternal', 'dad', 'parent'],
    'dob':     ['birth', 'born', 'birthday', 'date'],
    'birth':   ['dob', 'born', 'birthday'],
    'born':    ['dob', 'birth', 'birthday'],
    'zip':     ['pincode', 'pin', 'postal', 'postcode'],
    'pincode': ['zip', 'pin', 'postal', 'postcode'],
    'pin':     ['zip', 'pincode', 'postal'],
    'district':['taluk', 'tehsil', 'block'],
};

// Noise words stripped before comparison
const NOISE = /\b(your|my|the|enter|provide|please|full|own|personal|applicant|student|candidate|s)\b/g;

// Person-qualifiers: if the profile key has one of these, the form field
// MUST also contain it (or an alias). Prevents "Father's Name" filling "Name".
const PERSON_QUALIFIERS = {
    'father':   ['father', 'paternal', 'dad', 'f/o', 'fo'],
    'mother':   ['mother', 'maternal', 'mom', 'mum', 'm/o', 'mo'],
    'guardian': ['guardian', 'caretaker', 'legal'],
    'spouse':   ['spouse', 'husband', 'wife', 'partner'],
    'husband':  ['husband', 'spouse'],
    'wife':     ['wife', 'spouse'],
    'emergency':['emergency', 'alternate', 'secondary'],
};

function normalize(s) {
    return s
        .toLowerCase()
        .replace(/'/g, '')              // "father's" → "fathers"
        .replace(/[*?!:()\[\]]/g, '')
        .replace(/[-_/]/g, ' ')
        .replace(NOISE, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function expandAliases(words) {
    const result = new Set(words);
    for (const w of words) {
        if (SEMANTIC_ALIASES[w]) {
            SEMANTIC_ALIASES[w].forEach(a => result.add(a));
        }
    }
    return [...result];
}

// Returns the person-qualifier found in a profile key, or null.
function getPersonQualifier(profileKey) {
    const raw = profileKey.toLowerCase();
    for (const [qualifier, aliases] of Object.entries(PERSON_QUALIFIERS)) {
        if (raw.includes(qualifier)) return aliases;
    }
    return null;
}

function fieldsMatch(profileKey, attrOrLabel) {
    const kn = normalize(profileKey);
    const an = normalize(attrOrLabel);
    if (!an || an.length < 2) return false;

    const fieldText  = attrOrLabel.toLowerCase();
    const keyQual    = getPersonQualifier(profileKey);   // qualifier in profile key
    const fieldQual  = getPersonQualifier(attrOrLabel);  // qualifier in form field

    // Bidirectional person-qualifier guard:
    // "Father's Name" must NOT fill plain "Name" (keyQual present, field lacks it)
    if (keyQual && !keyQual.some(q => fieldText.includes(q))) return false;
    // "Full Name" must NOT fill "Father's Name" field (fieldQual present, key lacks it)
    if (fieldQual && !keyQual) return false;

    // If qualifier matched, check if field is a short abbreviation (F/O, M/O, DOB…)
    // In that case no long words remain after normalize → trust qualifier and match.
    if (keyQual && keyQual.some(q => fieldText.includes(q))) {
        const fieldLongWords = an.split(' ').filter(w => w.length > 2);
        if (fieldLongWords.length === 0) return true;  // pure abbreviation like F/O
    }

    // Direct substring match (after normalization)
    if (an.includes(kn) || kn.includes(an)) return true;

    // Word-level match with semantic aliases
    const kWords = expandAliases(kn.split(' ').filter(w => w.length > 2));
    const aWords = expandAliases(an.split(' ').filter(w => w.length > 2));
    return kWords.some(kw => aWords.some(aw => aw === kw || aw.includes(kw) || kw.includes(aw)));
}

function connect() {
    ws = new WebSocket('ws://127.0.0.1:5051');

    ws.onopen = () => {
        console.log('[iZACH] Connected.');
        ws.send(JSON.stringify({ type: 'client_hello', name: 'chrome_extension' }));
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'fill_form') {
                const inputs = document.querySelectorAll(
                    'input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
                );
                const inputCount = inputs.length;
                if (inputCount > 0) {
                    const filled = fillForm(msg.data || {});
                    console.log(`[iZACH] Found ${inputCount} inputs, filled ${filled}.`);
                    ws.send(JSON.stringify({ type: 'fill_result', filled, inputCount }));
                } else {
                    console.log('[iZACH] No form inputs found on this page.');
                    ws.send(JSON.stringify({ type: 'fill_result', filled: 0, inputCount: 0 }));
                }
            }
        } catch (e) {
            console.error('[iZACH] Error:', e);
        }
    };

    ws.onclose = () => { setTimeout(connect, 3000); };
    ws.onerror = () => { ws.close(); };
}

function fillForm(profile) {
    const inputs = document.querySelectorAll('input, textarea, select');
    let filled = 0;

    inputs.forEach(inp => {
        try {
            const type = (inp.type || '').toLowerCase();
            if (['hidden', 'submit', 'button', 'reset', 'image', 'checkbox', 'radio'].includes(type)) return;
            if (inp.value && inp.value.trim()) return;

            // Collect all matchable text for this field
            const rawAttrs = [
                inp.name || '',
                inp.id || '',
                inp.placeholder || '',
                inp.getAttribute('aria-label') || '',
                inp.getAttribute('autocomplete') || '',
                inp.getAttribute('data-field') || '',
            ];

            let labelText = '';
            if (inp.id) {
                try {
                    const label = document.querySelector(`label[for="${CSS.escape(inp.id)}"]`);
                    if (label) labelText = label.innerText || label.textContent || '';
                } catch (_) {}
            }
            const parentLabel = inp.closest('label');
            if (parentLabel) labelText += ' ' + (parentLabel.innerText || parentLabel.textContent || '');

            // Build matchable candidates
            const candidates = [...rawAttrs, labelText].filter(Boolean);

            // Try each profile key against all candidates
            let matchedVal = null;
            for (const [key, val] of Object.entries(profile)) {
                const hit = candidates.some(c => fieldsMatch(key, c));
                if (hit) {
                    matchedVal = val;
                    break;
                }
            }

            if (matchedVal !== null) {
                inp.focus();
                try {
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(inp, String(matchedVal));
                } catch (_) {
                    inp.value = String(matchedVal);
                }
                inp.dispatchEvent(new Event('input',  { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                try {
                    inp.dispatchEvent(new InputEvent('input', { bubbles: true, data: String(matchedVal) }));
                } catch (_) {}
                inp.blur();
                filled++;
            }
        } catch (e) {}
    });

    return filled;
}

connect();
