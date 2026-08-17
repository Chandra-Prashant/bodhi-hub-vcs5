/**
 * Starting state, and an optional demo project.
 *
 * The app opens EMPTY. Nothing is loaded, no assessment runs, and the header
 * shows no project until one exists — a tool that greets a new user with
 * somebody else's numbers is one they cannot trust, because they have no way
 * to tell which figures on screen are theirs.
 *
 * The sample is kept behind an explicit action for demos and for exercising
 * the assessment views without an upload.
 */

export const emptyProject = {
  name: "",
  proponent: "",
  country_iso2: "",
  technology: "SOLAR_PV_TERRESTRIAL",
  installed_capacity_mw: "",
  expected_annual_generation_mwh: "",
  initial_crediting_period_start: "",
  crediting_period_ordinal: 1,
  grid_connected: true,
  has_bess: false,
  grid_units: [],
  financials: null,
  similar_projects_all: 0,
  similar_projects_distinct: 0,
  regulatory_surplus: true,
  esg_entries: [],
};

/** Whether enough is filled in to run an assessment at all. */
export function isRunnable(project) {
  return Boolean(
    project.name &&
      project.proponent &&
      project.country_iso2 &&
      project.installed_capacity_mw &&
      project.expected_annual_generation_mwh &&
      project.initial_crediting_period_start
  );
}

/**
 * A worked example: 50 MW solar in Uttar Pradesh on a coal-heavy grid.
 * Real numbers — the grid units give a combined margin around 0.84 tCO2/MWh,
 * which is roughly where the Indian grid sits.
 */
export const sampleProject = {
  name: "Aligarh Solar One",
  proponent: "Bodhi Hub Client",
  country_iso2: "IN",
  technology: "SOLAR_PV_TERRESTRIAL",
  installed_capacity_mw: 50,
  expected_annual_generation_mwh: 87600,
  initial_crediting_period_start: "2026-03-01",
  crediting_period_ordinal: 1,
  grid_connected: true,
  has_bess: false,
  grid_units: [
    { unit_id: "COAL-1", generation_mwh: 50000, commissioning_year: 2012,
      efficiency: 0.35, efficiency_fuel_ef_t_per_gj: 0.0946 },
    { unit_id: "COAL-2", generation_mwh: 30000, commissioning_year: 2021,
      efficiency: 0.38, efficiency_fuel_ef_t_per_gj: 0.0946 },
    { unit_id: "GAS-1", generation_mwh: 10000, commissioning_year: 2023,
      efficiency: 0.52, efficiency_fuel_ef_t_per_gj: 0.0561 },
    { unit_id: "HYDRO-1", generation_mwh: 10000, commissioning_year: 2008,
      low_cost_must_run: true, generation_only: true },
  ],
  financials: {
    capex: 40000, annual_opex: 500, annual_generation_mwh: 87600,
    tariff_per_mwh: 0.03, project_lifetime_years: 25,
    discount_rate: 0.1, benchmark_irr: 0.14, credit_price_per_tco2e: 0.008,
  },
  similar_projects_all: 10,
  similar_projects_distinct: 9,
  regulatory_surplus: true,
  esg_entries: [],
};
