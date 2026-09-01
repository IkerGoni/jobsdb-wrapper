"""GraphQL operation documents for JobsDB (SEEK unified platform).

Reverse-engineered 2026-08-25 from th.jobsdb.com ca-search-ui bundles.
Endpoint: https://th.jobsdb.com/graphql
Requires header: x-custom-features: application/features.seek.all+json
"""

SEARCH_QUERY = """
query JobSearchV7($params: JobSearchV7QueryInput!, $locale: Locale!) {
  jobSearchV7(params: $params) {
    results {
      pagination {
        page
        pageSize
        resultCount
      }
      jobs {
        id
        title
        abstract
        adDisplay
        advertiser {
          id
          name
        }
        organisation {
          id
          name
          companyProfileId
          companyProfileUrl
        }
        categories {
          id
          label(locale: $locale)
        }
        location {
          id
          displayName {
            text
          }
        }
        salary {
          period
          min
          max
          currency
        }
        listedAt {
          dateTimeUtc
        }
        url
        workArrangements {
          id
          label {
            lang
            text
          }
        }
        tags {
          type
          label(locale: $locale)
        }
      }
    }
    enrichment {
      facets {
        categoryV1 {
          id
          count
          label {
            lang
            text
          }
        }
      }
      suggestions @include(if: true) {
        locationV1 {
          local {
            completions {
              id
              kind
            }
          }
          international {
            completions {
              id
              kind
            }
          }
        }
      }
    }
  }
}
"""

JOB_DETAIL_QUERY = """
query JobDetail($id: ID!) {
  jobDetails(id: $id) {
    job {
      id
      title
      abstract
      isExpired
      content
      advertiser {
        id
        name
      }
      salary {
        label
      }
      location {
        label
      }
      classifications {
        label(languageCode: "en")
      }
      categories {
        label
      }
      listedAt {
        dateTimeUtc
      }
      createdAt {
        dateTimeUtc
      }
    }
  }
}
"""
