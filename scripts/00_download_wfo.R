# Download World Flora Online backbone and filter to Orchidaceae.
#
# Run from project root:
#   Rscript scripts/00_download_wfo.R
#
# WFO.download() uses WFO's canonical backbone URL, which has drifted over
# the years (the backbone file has moved around). If the primary download
# fails, we fall back to a Zenodo mirror of the same DwC archive.
#
# NOTE: If R is not installed, scripts/05_clean_wfo.py implements the same
# Zenodo fallback directly in Python so this script can be skipped.

if (!requireNamespace("WorldFlora", quietly = TRUE)) {
  install.packages("WorldFlora", repos = "https://cloud.r-project.org")
}
library(WorldFlora)

wfo_dir <- "Chigualen/data/raw/wfo"
dir.create(wfo_dir, showWarnings = FALSE, recursive = TRUE)

zen_url <- "https://zenodo.org/records/18007552/files/_DwC_backbone_R.zip?download=1"

fetch_via_wfo <- function() {
  WFO.download(
    save.dir = wfo_dir,
    WFO.url = "http://www.worldfloraonline.org/downloadData/WFO_Backbone.zip"
  )
}

fetch_via_zenodo <- function() {
  zip_path <- file.path(wfo_dir, "backbone.zip")
  download.file(zen_url, zip_path, mode = "wb")
  unzip(zip_path, exdir = wfo_dir)
}

tryCatch(
  {
    cat("attempting WFO.download()...\n")
    fetch_via_wfo()
  },
  error = function(e) {
    cat("WFO.download() failed:", conditionMessage(e), "\n")
    cat("falling back to Zenodo mirror...\n")
    fetch_via_zenodo()
  }
)

# Find classification.txt, whether at top level or inside an unzipped subdir.
candidates <- list.files(
  wfo_dir, pattern = "classification\\.txt$",
  recursive = TRUE, full.names = TRUE
)
if (length(candidates) < 1) {
  stop("no classification.txt found under ", wfo_dir)
}
cat("reading", candidates[1], "\n")

wfo <- read.delim(
  candidates[1],
  sep = "\t",
  quote = "",
  na.strings = "",
  stringsAsFactors = FALSE
)

orchids <- wfo[!is.na(wfo$family) & wfo$family == "Orchidaceae", ]
cat("WFO total rows:", nrow(wfo), "\n")
cat("Orchidaceae rows:", nrow(orchids), "\n")

out_path <- "Chigualen/data/raw/wfo_orchids.csv"
write.csv(orchids, out_path, row.names = FALSE)
cat("wrote", nrow(orchids), "rows to", out_path, "\n")
