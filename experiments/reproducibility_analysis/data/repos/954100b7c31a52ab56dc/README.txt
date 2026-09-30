================
Directory layout
================

./DB/              # Database schemas etc
  Virtuoso/
    ATLAS.owl
  Impala
    dkb_schema.sql

./Utils/           # Data and database management scripts
  Virtuoso/
    load_ontology.sh
    create_graph.sh
  Impala/
    create_dkb.sh
  Dataflow/
    StageX/
      README         # Description of input, tmp and output files
      stagex.sh
      stagex.py
    README         # Dataflow description
    config/        # Common directory for the stage configs
  Elasticsearch/   # Tools for working with elasticsearch
    config/        # ES config files

./DataSamples/     # Data samples for dataflow scripts
  input/
     StageX/
  output/
     StageX/
  tmp/
     StageX/

./DatasetDiscovery # all information about datasets, theirs parameters, Oracle/AMI/RUCIO 		   # requests

./README           # This file

========
Dataflow
========

It is suggested to treat all the data management scripts as a consequent steps 
of the dataflow.
For example:
1)   Get papers with links to supporting documents from GLANCE
  input/...  (please fill if aware)
  output/... (please fill if aware)
2)   Get papers metadata from CDS
  input/...  (please fill if aware)
  output/... (please fill if aware)
3)   Get supporting notes metadata from CDS
  input/...  (please fill if aware)
  output/... (please fill if aware)
4)   Download Supporting Notes PDF papers from CDS: 
  input/...  (please fill if aware)
  output/... (please fill if aware)
5)   Get PDF URLs from CDS
  input/...  (please fill if aware)
  output/... (please fill if aware)
6)   Convert PDF to a text file:
  input/PDF_Analyzer  -> (step 5 output)
  output/PDF_Analyzer           -- JSON files
7.1) Convert paper metadata to triples:
  input/preparePapers -> (step 2 output)
  output/preparePapers/ttl      -- TTL and...
  output/preparePapers/sparql   -- ...SPARQL files
7.2) Convert SupportingDocuments metadata to triples:
  input/prepareSDocs -> output/PDF_Analyzer
  output/preparSDocs/ttl         -- TTL and...
  output/prepareSDocs/sparql     -- ...SPARQL files
7.2) Get dataset metadata:
  input/ds_get_metadata -> output/parseTXT
  output/ds_get_metadata        -- CSV files
8)   Convert dataset metadata to triples:
  input/prepareDatasets -> output/ds_get_metadata
  output/prepareDatasets/ttl    -- TTL and...
  output/prepareDatasets/sparql -- ...SPARQL files
9)   Upload data to Virtuoso:
  input/upload2Virtuoso -> output/prepare*/*
  output/upload2Virtuoso         -- empty
