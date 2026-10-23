# Regenerates the committed metafor fixtures in tests/statistical/fixtures/ (openspec:test-suite#statistical-validation).
#
#   Rscript tests/statistical/generate.R
#
# The Python suite compares the native engine with these files and needs no R. The nightly
# `metafor-live` job runs this script again and fails on any drift (`git diff --exit-code`), so the
# files carry no timestamps and no version strings, and every number is written with 17 significant
# digits. Where strata deliberately differs from metafor's default, the call here pins the matching
# option and says why.

suppressMessages(library(metafor))

# ---- a tiny deterministic JSON writer (no dependency) -------------------------------------------------

num <- function(x) {
  if (is.na(x) || is.nan(x) || is.infinite(x)) return("null")
  s <- sprintf("%.17g", x)
  if (grepl("^-?[0-9]+$", s)) s <- paste0(s, ".0")
  s
}
esc <- function(s) {
  s <- gsub("\\\\", "\\\\\\\\", s)
  s <- gsub("\"", "\\\\\"", s)
  paste0("\"", s, "\"")
}
tojson <- function(x, indent = 0) {
  pad <- strrep("  ", indent)
  pad1 <- strrep("  ", indent + 1)
  if (is.null(x)) return("null")
  if (is.list(x)) {
    if (length(x) == 0) return(if (is.null(names(x))) "[]" else "{}")
    if (!is.null(names(x))) {
      body <- vapply(seq_along(x), function(i) paste0(pad1, esc(names(x)[i]), ": ", tojson(x[[i]], indent + 1)), "")
      return(paste0("{\n", paste(body, collapse = ",\n"), "\n", pad, "}"))
    }
    if (all(vapply(x, function(v) !is.list(v) && length(v) == 1, TRUE))) {
      return(paste0("[", paste(vapply(x, function(v) tojson(v, indent + 1), ""), collapse = ", "), "]"))
    }
    body <- vapply(x, function(v) paste0(pad1, tojson(v, indent + 1)), "")
    return(paste0("[\n", paste(body, collapse = ",\n"), "\n", pad, "]"))
  }
  if (is.character(x)) {
    if (length(x) == 1) return(esc(x))
    return(paste0("[", paste(vapply(x, esc, ""), collapse = ", "), "]"))
  }
  if (is.logical(x)) {
    v <- ifelse(is.na(x), "null", ifelse(x, "true", "false"))
    return(if (length(x) == 1) v else paste0("[", paste(v, collapse = ", "), "]"))
  }
  v <- vapply(as.numeric(x), num, "")
  if (length(x) == 1) v else paste0("[", paste(v, collapse = ", "), "]")
}
write_fixture <- function(name, obj) {
  dir.create("tests/statistical/fixtures", showWarnings = FALSE, recursive = TRUE)
  writeLines(tojson(obj), file.path("tests/statistical/fixtures", paste0(name, ".json")))
}
arr <- function(x) as.list(as.numeric(x))   # force a JSON array even for length 1

# ---- datasets -------------------------------------------------------------------------------------------

bcg <- escalc(measure = "RR", ai = tpos, bi = tneg, ci = cpos, di = cneg, data = dat.bcg)
rau <- dat.raudenbush1985
hack <- dat.hackshaw1998

pooling_cases <- list(
  # Colditz et al. (1994) BCG vaccine trials, log risk ratio: the standard worked example.
  bcg_logrr = list(yi = bcg$yi, vi = bcg$vi),
  # Raudenbush (1985) teacher expectancy: SMDs with a known small tau^2.
  raudenbush = list(yi = rau$yi, vi = rau$vi),
  # Hackshaw et al. (1998), passive smoking and lung cancer, log OR.
  hackshaw = list(yi = hack$yi, vi = hack$vi),
  # Synthetic edge cases required by openspec:test-suite#statistical-validation.
  k2 = list(yi = c(0.30, 0.55), vi = c(0.04, 0.06)),
  k3 = list(yi = c(0.10, 0.45, 0.80), vi = c(0.05, 0.03, 0.08)),
  homogeneous = list(yi = c(0.20, 0.22, 0.19, 0.21, 0.20), vi = c(0.02, 0.03, 0.025, 0.04, 0.03)),
  identical_vi = list(yi = c(0.1, 0.5, 0.9, 0.3, 0.7), vi = rep(0.04, 5)),
  dominant_weight = list(yi = c(0.40, 0.10, 0.90, 0.50, 0.20), vi = c(0.0004, 0.5, 0.6, 0.4, 0.7)),
  heterogeneous = list(yi = c(-0.8, 0.1, 1.2, 0.6, -0.3, 1.5, 0.2), vi = c(0.05, 0.08, 0.04, 0.06, 0.09, 0.07, 0.05))
)
methods <- c("DL", "HE", "HS", "SJ", "ML", "REML", "EB", "PM")
tests <- c("z", "knha", "adhoc")

# Tight convergence so the comparison measures the algorithm, not metafor's default stopping rule
# (threshold = 1e-5): the spec's 1e-6 tolerance for iterative tau^2 needs metafor converged too.
tight <- list(threshold = 1e-12, maxiter = 2000, tol = 1e-12)

fit_summary <- function(res) {
  k <- res$k
  p <- res$p
  qe <- res$QE
  list(
    k = k,
    beta = arr(res$beta), se = arr(res$se), zval = arr(res$zval), pval = arr(res$pval),
    ci_lb = arr(res$ci.lb), ci_ub = arr(res$ci.ub),
    tau2 = res$tau2, QE = qe, QEp = res$QEp,
    # strata reports the Q-based I^2 and H^2 (openspec:pooling-models#heterogeneity-and-prediction-intervals);
    # metafor's own I^2 and H^2 for a random-effects model are tau^2-based, kept here under their own names.
    I2 = if (k > p) max(0, 100 * (qe - (k - p)) / qe) else 0,
    H2 = if (k > p) qe / (k - p) else 1,
    I2_metafor = res$I2, H2_metafor = res$H2
  )
}

pooling <- list()
for (nm in names(pooling_cases)) {
  d <- pooling_cases[[nm]]
  case <- list(yi = arr(d$yi), vi = arr(d$vi), fits = list())
  fe <- rma(d$yi, d$vi, method = "FE")
  case$fits[["FE"]] <- fit_summary(fe)
  for (m in methods) {
    for (tst in tests) {
      key <- paste(m, tst, sep = "|")
      res <- tryCatch(rma(d$yi, d$vi, method = m, test = tst, control = tight), error = function(e) NULL)
      if (is.null(res)) next
      s <- fit_summary(res)
      # Prediction interval: Riley et al. (2011), a t distribution on k-2 df. metafor's default
      # (k-p df) differs from strata's documented convention, so the matching option is pinned here.
      if (length(d$yi) >= 3) {
        pr <- predict(res, pi.type = "Riley")
        s$pi_lb <- pr$pi.lb
        s$pi_ub <- pr$pi.ub
      }
      # Q-profile confidence interval for tau^2. It depends only on the data, not on which estimator
      # produced the point estimate, so it is requested explicitly (type = "QP": metafor would use the
      # profile likelihood for ML/REML) with an upper search limit far beyond any bound here.
      if (m != "FE") {
        ci <- tryCatch(confint(res, type = "QP", control = list(tol = 1e-12, maxiter = 2000, tau2.max = 1e6)),
                       error = function(e) NULL)
        if (!is.null(ci)) {
          s$tau2_ci_lb <- ci$random["tau^2", "ci.lb"]
          s$tau2_ci_ub <- ci$random["tau^2", "ci.ub"]
          s$tau_ci_lb <- ci$random["tau", "ci.lb"]
          s$tau_ci_ub <- ci$random["tau", "ci.ub"]
        }
      }
      case$fits[[key]] <- s
    }
  }
  pooling[[nm]] <- case
}
write_fixture("pooling", pooling)

# ---- meta-regression -----------------------------------------------------------------------------------

bcg$alloc <- factor(dat.bcg$alloc, levels = c("random", "alternate", "systematic"))
meta_regression <- list()
reg_cases <- list(
  bcg_ablat = list(data = bcg, formula = ~ ablat),
  bcg_ablat_year = list(data = bcg, formula = ~ ablat + year),
  bcg_alloc = list(data = bcg, formula = ~ alloc),
  bcg_ablat_alloc = list(data = bcg, formula = ~ ablat + alloc),
  raudenbush_weeks = list(data = cbind(rau, yi = rau$yi), formula = ~ weeks)
)
for (nm in names(reg_cases)) {
  rc <- reg_cases[[nm]]
  X <- model.matrix(rc$formula, data = rc$data)
  case <- list(yi = arr(rc$data$yi), vi = arr(rc$data$vi),
               X = lapply(seq_len(nrow(X)), function(i) arr(X[i, ])),
               columns = colnames(X), fits = list())
  for (m in c("DL", "REML", "ML")) {
    for (tst in c("z", "knha", "adhoc")) {
      res <- rma(rc$data$yi, rc$data$vi, mods = rc$formula, data = rc$data, method = m, test = tst, control = tight)
      s <- fit_summary(res)
      s$QM <- res$QM
      s$QMp <- res$QMp
      s$R2 <- res$R2
      s$QE_df <- res$k - res$p
      case$fits[[paste(m, tst, sep = "|")]] <- s
    }
  }
  meta_regression[[nm]] <- case
}
write_fixture("meta_regression", meta_regression)

# ---- publication bias and small-study effects ---------------------------------------------------------------

egger01 <- escalc(measure = "OR", ai = ai, n1i = n1i, ci = ci, n2i = n2i, data = dat.egger2001)
bias_sets <- list(
  bcg_logrr = list(yi = bcg$yi, vi = bcg$vi),
  hackshaw = list(yi = hack$yi, vi = hack$vi),
  raudenbush = list(yi = rau$yi, vi = rau$vi),
  # Log odds ratios from 2x2 tables (events, n per arm): Harbord's and Peters' tests need the counts.
  egger2001_logor = list(yi = egger01$yi, vi = egger01$vi,
                         ai = dat.egger2001$ai, n1i = dat.egger2001$n1i, ci = dat.egger2001$ci, n2i = dat.egger2001$n2i)
)

wls_summary <- function(y, x, w) {
  fit <- lm(y ~ x, weights = w)
  co <- summary(fit)$coefficients
  list(intercept = co[1, 1], intercept_se = co[1, 2], intercept_t = co[1, 3], intercept_p = co[1, 4],
       slope = co[2, 1], slope_se = co[2, 2], slope_t = co[2, 3], slope_p = co[2, 4], df = fit$df.residual)
}

bias <- list()
for (nm in names(bias_sets)) {
  d <- bias_sets[[nm]]
  res <- rma(d$yi, d$vi, method = "REML", control = tight)
  k <- length(d$yi)
  case <- list(yi = arr(d$yi), vi = arr(d$vi))
  if (!is.null(d$ai)) case[c("ai", "n1i", "ci", "n2i")] <- list(arr(d$ai), arr(d$n1i), arr(d$ci), arr(d$n2i))
  # Egger's regression test, in metafor's weighted-regression form (the slope on sei is Egger's intercept).
  case$egger <- wls_summary(d$yi, sqrt(d$vi), 1 / d$vi)
  # Begg and Mazumdar's rank correlation (Kendall's tau between standardised effects and variances).
  rk <- suppressWarnings(ranktest(res))
  case$begg <- list(tau = unname(rk$tau), pval = rk$pval)
  # Trim-and-fill, the three estimators; fitted with the random-effects REML model, as strata does.
  tf <- list()
  for (est in c("L0", "R0", "Q0")) {
    t <- tryCatch(suppressWarnings(trimfill(res, estimator = est)), error = function(e) NULL)
    if (is.null(t)) { message("trimfill ", est, " failed on ", nm); next }   # not part of the fixture
    filled <- which(t$fill)
    # trimfill() re-pools the completed data with metafor's default convergence threshold (1e-5), so the
    # pooled estimate is recomputed here on the same completed data with tight control.
    fin <- rma(c(d$yi, t$yi[filled]), c(d$vi, t$vi[filled]), method = "REML", control = tight)
    tf[[est]] <- list(k0 = t$k0, side = t$side, beta = arr(fin$beta), se = arr(fin$se), tau2 = fin$tau2,
                      yi_filled = arr(t$yi[filled]), vi_filled = arr(t$vi[filled]))
  }
  case$trimfill <- tf
  # PET and PEESE: weighted regressions of the effect on its standard error / variance (weights 1/vi,
  # multiplicative residual variance, t on k-2 df), the intercept being the "no small-study effect" estimate.
  case$pet <- wls_summary(d$yi, sqrt(d$vi), 1 / d$vi)
  case$peese <- wls_summary(d$yi, d$vi, 1 / d$vi)
  if (!is.null(d$ai)) {
    a <- as.numeric(d$ai); n1 <- as.numeric(d$n1i); cc <- as.numeric(d$ci); n2 <- as.numeric(d$n2i)
    n <- n1 + n2; m1 <- a + cc; m0 <- n - m1
    # Peters et al. (2006): ln(OR) on 1/n, weights m1*m0/n. metafor does not provide this test.
    case$peters <- wls_summary(d$yi, 1 / n, m1 * m0 / n)
    # Harbord et al. (2006): the score statistic Z with variance V; regress Z/sqrt(V) on sqrt(V), test the intercept.
    e <- n1 * m1 / n
    v <- n1 * n2 * m1 * m0 / (n^2 * (n - 1))
    case$harbord <- wls_summary((a - e) / sqrt(v), sqrt(v), rep(1, k))
  }
  bias[[nm]] <- case
}
write_fixture("bias", bias)

# ---- leave-one-out, influence, cumulative ----------------------------------------------------------------------

diag_sets <- list(
  bcg_logrr = list(yi = bcg$yi, vi = bcg$vi, year = dat.bcg$year),
  raudenbush = list(yi = rau$yi, vi = rau$vi, year = rau$year),
  hackshaw = list(yi = hack$yi, vi = hack$vi, year = hack$year),
  k5 = list(yi = c(0.1, 0.4, 0.35, 1.4, 0.2), vi = c(0.05, 0.04, 0.06, 0.05, 0.03), year = c(2001, 2003, 2002, 2005, 2004))
)
diagnostics <- list()
for (nm in names(diag_sets)) {
  d <- diag_sets[[nm]]
  case <- list(yi = arr(d$yi), vi = arr(d$vi), year = arr(d$year), fits = list())
  for (tst in c("z", "adhoc")) {
    res <- rma(d$yi, d$vi, method = "REML", test = tst, control = tight)
    inf <- influence(res)
    l1 <- leave1out(res, control = tight)
    # Cumulative meta-analysis in the order given (here: by year, ties in input order).
    o <- order(d$year, seq_along(d$year))
    cu <- cumul(res, order = d$year, control = tight)
    qe_i2 <- function(Q, df) if (df > 0) pmax(0, 100 * (Q - df) / Q) else rep(0, length(Q))
    case$fits[[tst]] <- list(
      influence = list(
        rstudent = arr(inf$inf$rstudent), dffits = arr(inf$inf$dffits), cook_d = arr(inf$inf$cook.d),
        cov_r = arr(inf$inf$cov.r), tau2_del = arr(inf$inf$tau2.del), QE_del = arr(inf$inf$QE.del),
        hat = arr(inf$inf$hat), weight = arr(inf$inf$weight), dfbs = arr(inf$dfbs[[1]])
      ),
      leave_one_out = list(
        estimate = arr(l1$estimate), se = arr(l1$se), ci_lb = arr(l1$ci.lb), ci_ub = arr(l1$ci.ub),
        tau2 = arr(l1$tau2), Q = arr(l1$Q), I2 = arr(qe_i2(l1$Q, length(d$yi) - 2))
      ),
      cumulative = list(
        order = arr(o),
        estimate = arr(cu$estimate), se = arr(cu$se), ci_lb = arr(cu$ci.lb), ci_ub = arr(cu$ci.ub),
        tau2 = arr(cu$tau2), Q = arr(cu$Q)
      )
    )
  }
  diagnostics[[nm]] <- case
}
write_fixture("diagnostics", diagnostics)

# ---- dependent effect sizes ----------------------------------------------------------------------------------
# Assink & Wibbelink (2016) delinquency data: 100 effects in 17 studies. Konstantopoulos (2011): 56 studies
# in 11 districts (a classic three-level example).

suppressMessages(library(clubSandwich))
assink <- dat.assink2016
kons <- dat.konstantopoulos2011
mv_control <- list(optimizer = "nlminb", rel.tol = 1e-11, iter.max = 1000, eval.max = 2000)

cr2_summary <- function(rob) {
  list(beta = arr(rob$beta), se = arr(rob$se), tval = arr(rob$zval), df = arr(rob$dfs), pval = arr(rob$pval),
       ci_lb = arr(rob$ci.lb), ci_ub = arr(rob$ci.ub))
}

dependence <- list()

# Aggregation within study (Borenstein et al. 2009): the unweighted mean of a study's effects with the
# variance of that mean under compound symmetry with correlation rho. aggregate.escalc() does this when
# told not to weight (weighted = FALSE) and given struct = "CS".
dat <- escalc(measure = "GEN", yi = yi, vi = vi, data = assink)
agg <- list()
for (rho in c(0.2, 0.5, 0.8)) {
  a <- aggregate(dat, cluster = dat$study, struct = "CS", rho = rho, weighted = FALSE)
  agg[[as.character(rho)]] <- list(study = arr(a$study), yi = arr(a$yi), vi = arr(a$vi))
}
dependence$assink_aggregate <- list(study = arr(assink$study), yi = arr(assink$yi), vi = arr(assink$vi), results = agg)

# Cluster-robust inference (CR2 with Satterthwaite degrees of freedom) around the ordinary random-effects
# model, i.e. with independent working errors.
re <- rma(yi, vi, data = assink, method = "REML", control = tight)
dependence$assink_re_cr2 <- list(
  yi = arr(assink$yi), vi = arr(assink$vi), study = arr(assink$study),
  tau2 = re$tau2, fit = cr2_summary(robust(re, cluster = assink$study, clubSandwich = TRUE))
)

# The correlated-and-hierarchical-effects (CHE) working model: sampling errors correlated at rho within a
# study, a random effect for the study and one for each effect, fitted by REML; then CR2 on top.
che <- list()
for (rho in c(0.2, 0.5, 0.8)) {
  V <- vcalc(vi, cluster = study, obs = esid, rho = rho, data = assink)
  mv <- rma.mv(yi, V, random = ~ 1 | study / esid, data = assink, method = "REML", control = mv_control)
  che[[as.character(rho)]] <- list(
    sigma2 = arr(mv$sigma2), beta = arr(mv$beta), se = arr(mv$se), ll = as.numeric(logLik(mv)),
    cr2 = cr2_summary(robust(mv, cluster = assink$study, clubSandwich = TRUE))
  )
}
dependence$assink_che <- list(yi = arr(assink$yi), vi = arr(assink$vi), study = arr(assink$study),
                              esid = arr(assink$esid), results = che)

# Three-level model: studies within districts, independent sampling errors.
mv3 <- rma.mv(yi, vi, random = ~ 1 | district / study, data = kons, method = "REML", control = mv_control)
dependence$konstantopoulos_three_level <- list(
  yi = arr(kons$yi), vi = arr(kons$vi), district = arr(kons$district), study = arr(kons$study),
  sigma2 = arr(mv3$sigma2), beta = arr(mv3$beta), se = arr(mv3$se), ll = as.numeric(logLik(mv3)),
  cr2 = cr2_summary(robust(mv3, cluster = kons$district, clubSandwich = TRUE))
)
write_fixture("dependence", dependence)
