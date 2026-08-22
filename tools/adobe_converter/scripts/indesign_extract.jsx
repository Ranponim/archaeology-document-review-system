#target "InDesign"

/*
 * Structural InDesign extractor for ReferenceCorpus builds.
 *
 * This script deliberately does not interpret publication identifiers. It
 * reports DOM textFrames, graphics and actual Link placement only; canonical
 * Plate/PlatePanel identity is created later by ReferenceCanonicalizer.
 */
(function () {
    function readUtf8(path) {
        var file = File(path);
        file.encoding = "UTF-8";
        if (!file.open("r")) { throw new Error("Cannot open context: " + path); }
        var text = file.read();
        file.close();
        return text;
    }

    function writeUtf8(path, text) {
        var file = File(path);
        file.encoding = "UTF-8";
        if (!file.open("w")) { throw new Error("Cannot write manifest: " + path); }
        file.write(text);
        file.close();
    }

    function parseJson(text) {
        if (typeof JSON !== "undefined" && JSON.parse) { return JSON.parse(text); }
        return eval("(" + text + ")");
    }

    function stringifyJson(value) {
        if (typeof JSON !== "undefined" && JSON.stringify) { return JSON.stringify(value, null, 2); }
        throw new Error("JSON.stringify is required by the Adobe extractor");
    }

    function numberArray(bounds) {
        if (!bounds || bounds.length !== 4) { return null; }
        return [Number(bounds[0]), Number(bounds[1]), Number(bounds[2]), Number(bounds[3])];
    }

    function safeId(item, fallback) {
        try {
            if (item && item.id !== undefined && item.id !== null) { return String(item.id); }
        } catch (_ignored) {}
        return fallback;
    }

    function safeContents(frame) {
        try { return String(frame.contents || ""); } catch (_ignored) { return ""; }
    }

    function safeBounds(item) {
        try { return numberArray(item.geometricBounds); } catch (_ignored) { return null; }
    }

    function collectTextFrames(page) {
        var result = [];
        var frames;
        try { frames = page.textFrames.everyItem().getElements(); }
        catch (_error) { frames = page.textFrames; }
        for (var i = 0; i < frames.length; i += 1) {
            result.push({
                objectId: safeId(frames[i], "textFrame:" + i),
                text: safeContents(frames[i]),
                bounds: safeBounds(frames[i])
            });
        }
        return result;
    }

    function collectGraphics(page) {
        var result = [];
        var graphics = [];
        try { graphics = page.allGraphics; } catch (_error) { graphics = []; }
        for (var i = 0; i < graphics.length; i += 1) {
            var graphic = graphics[i];
            var frame = null;
            try { frame = graphic.parent; } catch (_ignoredParent) {}
            var link = null;
            try { link = graphic.itemLink; } catch (_ignoredLink) {}
            var linkId = null;
            var linkPath = null;
            if (link && link.isValid !== false) {
                try { linkId = safeId(link, null); } catch (_ignoredLinkId) {}
                try { linkPath = String(link.filePath || ""); } catch (_ignoredPath) {}
            }
            result.push({
                objectId: safeId(graphic, "graphic:" + i),
                bounds: safeBounds(frame || graphic),
                linkId: linkId,
                linkPath: linkPath
            });
        }
        return result;
    }

    var contextPath = $.getenv("ARCHAEOLOGY_ADOBE_CONTEXT");
    if (!contextPath) { throw new Error("ARCHAEOLOGY_ADOBE_CONTEXT is required"); }
    var context = parseJson(readUtf8(contextPath));
    var sourceFile = File(context.sourcePath);
    if (!sourceFile.exists) { throw new Error("InDesign source does not exist"); }

    var document = null;
    try {
        document = app.open(sourceFile, false);
        var pages = [];
        for (var p = 0; p < document.pages.length; p += 1) {
            var page = document.pages[p];
            pages.push({
                index: p,
                label: String(page.name || ""),
                textFrames: collectTextFrames(page),
                graphics: collectGraphics(page)
            });
        }

        var artifacts = [];
        var pdfPath = Folder(context.outputDir).fsName + "/" + context.sourceAssetId + ".pdf";
        try {
            var pdfFile = File(pdfPath);
            document.exportFile(ExportFormat.PDF_TYPE, pdfFile, false);
            if (pdfFile.exists) {
                artifacts.push({type: "pdf", path: pdfFile.fsName, mimeType: "application/pdf"});
            }
        } catch (_renderError) {
            // A missing preview must not alter identity facts. Build validation
            // can decide whether a render artifact is mandatory for deployment.
        }

        var manifest = {
            schemaVersion: Number(context.schemaVersion || 1),
            application: "indesign",
            applicationVersion: String(app.version || ""),
            sourceAssetId: String(context.sourceAssetId),
            sourceSha256: String(context.sourceSha256),
            pages: pages,
            artboards: [],
            artifacts: artifacts
        };
        writeUtf8(context.manifestPath, stringifyJson(manifest));
    } finally {
        if (document) {
            try { document.close(SaveOptions.NO); } catch (_closeError) {}
        }
    }
}());
