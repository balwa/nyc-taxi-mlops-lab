# notebooks/

`explore.ipynb` (given in S2) runs on the lab's SageMaker notebook (`infra/modules/notebook`, wired in S2): the backstory, a look at the data through the Redshift Data API, and the static median vs v1 vs v2 on the same holdout, using `tripmodel` from `pipelines/src`. Notebook runs log to their own MLflow experiment (`trip-duration-notebook`); only the pipeline registers models. What moves out of the notebook into the pipeline is decision record 007.

`requirements.txt` is installed into the `conda_python3` kernel at every notebook start.
