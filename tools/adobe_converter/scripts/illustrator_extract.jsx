#target "Illustrator"

/*
 * Structural Illustrator extractor for ReferenceCorpus builds.
 *
 * This script reports artboards, textFrames and placedItems. It never derives
 * Drawing/DrawingRegion publication identity from a filename or text pattern;
 * ReferenceCanonicalizer owns that deterministic interpretation.
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

    function normalizedBox(bounds) {
        if (!bounds || bounds.length !== 4) { return null; }
        var x0 = Math.min(Number(bounds[0]), Number(bounds[2]));
        var x1 = Math.max(Number(bounds[0]), Number(bounds[2]));
        var y0 = Math.min(Number(bounds[1]), Number(bounds[3]));
        var y1 = Math.max(Number(bounds[1]), Number(bounds[3]));
        return [x0, y0, x1, y1];
    }

    function center(bounds) {
        var box = normalizedBox(bounds);
        if (!box) { return null; }
        return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
    }

    function contains(rect, point) {
        var box = normalizedBox(rect);
        return !!(box && point && point[0] >= box[0] && point[0] <= box[2] && point[1] >= box[1] && point[1] <= box[3]);
    }

    function safeBounds(item) {
        try { return numberArray(item.visibleBounds); }
        catch (_visibleError) {
            try { return numberArray(item.geometricBounds); } catch (_geometryError) { return null; }
        }
    }

    function safeName(item, fallback) {
        try {
            if (item.name) { return String(item.name); }
        } catch (_ignored) {}
        return fallback;
    }

    function collectTextFrames(document, artboardRect) {
        var result = [];
        for (var i = 0; i < document.textFrames.length; i += 1) {
            var frame = document.textFrames[i];
            var bounds = safeBounds(frame);
            if (!contains(artboardRect, center(bounds))) { continue; }
            var text = "";
            try { text = String(frame.contents || ""); } catch (_ignoredText) {}
            result.push({
                objectId: safeName(frame, "textFrame:" + i),
                text: text,
                bounds: bounds
            });
        }
        return result;
    }

    function collectPlacedItems(document, artboardRect) {
        var result = [];
        for (var i = 0; i < document.placedItems.length; i += 1) {
            var item = document.placedItems[i];
            var bounds = safeBounds(item);
            if (!contains(artboardRect, center(bounds))) { continue; }
            var linkPath = null;
            try {
                if (item.file) { linkPath = String(item.file.fsName); }
            } catch (_ignoredFile) {}
            result.push({
                objectId: safeName(item, "placedItem:" + i),
                bounds: bounds,
                linkId: null,
                linkPath: linkPath
            });
        }
        return result;
    }

    var contextPath = $.getenv("ARCHAEOLOGY_ADOBE_CONTEXT");
    if (!contextPath) { throw new Error("ARCHAEOLOGY_ADOBE_CONTEXT is required"); }
    var context = parseJson(readUtf8(contextPath));
    var sourceFile = File(context.sourcePath);
    if (!sourceFile.exists) { throw new Error("Illustrator source does not exist"); }

    var document = null;
    try {
        document = app.open(sourceFile);
        var artboards = [];
        var artifacts = [];
        for (var a = 0; a < document.artboards.length; a += 1) {
            var artboard = document.artboards[a];
            var rect = numberArray(artboard.artboardRect);
            artboards.push({
                index: a,
                name: String(artboard.name || ""),
                textFrames: collectTextFrames(document, rect),
                placedItems: collectPlacedItems(document, rect)
            });

            try {
                document.artboards.setActiveArtboardIndex(a);
                var pngOptions = new ExportOptionsPNG24();
                pngOptions.artBoardClipping = true;
                pngOptions.antiAliasing = true;
                pngOptions.transparency = true;
                var pngPath = Folder(context.outputDir).fsName + "/" + context.sourceAssetId + "-artboard-" + (a + 1) + ".png";
                var pngFile = File(pngPath);
                document.exportFile(pngFile, ExportType.PNG24, pngOptions);
                if (pngFile.exists) {
                    artifacts.push({type: "png", path: pngFile.fsName, mimeType: "image/png"});
                }
            } catch (_renderError) {
                // Render availability does not alter the extracted DOM facts.
            }
        }

        var manifest = {
            schemaVersion: Number(context.schemaVersion || 1),
            application: "illustrator",
            applicationVersion: String(app.version || ""),
            sourceAssetId: String(context.sourceAssetId),
            sourceSha256: String(context.sourceSha256),
            pages: [],
            artboards: artboards,
            artifacts: artifacts
        };
        writeUtf8(context.manifestPath, stringifyJson(manifest));
    } finally {
        if (document) {
            try { document.close(SaveOptions.DONOTSAVECHANGES); } catch (_closeError) {}
        }
    }
}());
